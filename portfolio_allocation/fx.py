"""Daily central-bank rates, immutable raw responses, explicit missing-data errors.

All rates are USD per one native unit. Execution rates affect FX cash legs;
central-bank observations value the remaining native cash at each state.
"""
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from .models import D


class MissingFX(ValueError):
    pass


class FX:
    def __init__(self, cache_dir, max_staleness_days=14):
        self.path = Path(cache_dir)
        self.path.mkdir(parents=True,exist_ok=True)
        self.cache_file = self.path / 'rates.json'
        self.rows = json.loads(self.cache_file.read_text(encoding='utf-8')) if self.cache_file.exists() else {}
        self.max_staleness_days = max_staleness_days
        self.usage = {}
        self._index()

    def _index(self):
        self.dates = {c:sorted(rows) for c,rows in self.rows.items()}

    def add(self, currency, day, rate, source, source_url=''):
        if D(rate) <= 0:
            raise ValueError('FX must be strictly positive')
        self.rows.setdefault(currency,{})[str(day)] = {'rate':str(rate),'source':source,'url':source_url}
        self._index()

    def rate(self, currency, day):
        day = day.date() if isinstance(day,datetime) else day
        if currency=='USD':
            return D(1), {'requested_date':str(day),'rate_date':str(day),'rate':'1','source':'USD numeraire'}
        days = self.dates.get(currency,[])
        index = bisect_right(days,str(day))-1
        if index < 0:
            raise MissingFX(f'No preceding {currency}/USD rate for {day}')
        used = days[index]
        age = (day-date.fromisoformat(used)).days
        if age > self.max_staleness_days:
            raise MissingFX(f'{currency}/USD observation {used} is {age} days old on {day}; refusing stale valuation')
        record = dict(self.rows[currency][used],requested_date=str(day),rate_date=used,age_days=age)
        self.usage[(currency,str(day))] = dict(currency=currency,**record)
        return D(record['rate']),record

    def usd(self, amount, currency, day):
        if D(amount)==0:
            return D(0)
        return D(amount)*self.rate(currency,day)[0]

    def _download(self, url, name):
        raw_path = self.path / name
        if raw_path.exists():
            return raw_path.read_bytes()
        raw = urlopen(Request(url,headers={'User-Agent':'PortfolioAllocation/1.0 (historical research)'}),timeout=25).read()
        # Do not cache an HTML error as a successful rate response.
        ET.fromstring(raw)
        raw_path.write_bytes(raw)
        metadata = {'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),
                    'sha256':hashlib.sha256(raw).hexdigest()}
        raw_path.with_suffix(raw_path.suffix+'.meta.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        return raw

    def download_ecb(self):
        url = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml'
        root = ET.fromstring(self._download(url,'ecb-eurofxref-hist.xml'))
        for node in root.iter():
            if 'time' not in node.attrib:
                continue
            rates = {n.attrib['currency']:D(n.attrib['rate']) for n in node if 'currency' in n.attrib}
            if 'USD' not in rates:
                continue
            day = node.attrib['time']
            self.rows.setdefault('EUR',{})[day] = {'rate':str(rates['USD']),'source':'ECB reference','url':url}
            for currency,per_eur in rates.items():
                if currency != 'USD':
                    self.rows.setdefault(currency,{})[day] = {'rate':str(rates['USD']/per_eur),'source':'ECB cross via EUR','url':url}
        self.save()

    def download_cbr(self,start,end):
        # CBR dates are effective published dates, including Saturdays. ECB EUR
        # remains the primary EUR series; RUB uses official RUB per USD directly.
        params = urlencode({'date_req1':start.strftime('%d/%m/%Y'),
                            'date_req2':end.strftime('%d/%m/%Y'),'VAL_NM_RQ':'R01235'})
        url = 'https://www.cbr.ru/scripts/XML_dynamic.asp?'+params
        root = ET.fromstring(self._download(url,f'cbr-usd-{start}-{end}.xml'))
        for node in root.findall('Record'):
            day = datetime.strptime(node.attrib['Date'],'%d.%m.%Y').date().isoformat()
            nominal = D(node.findtext('Nominal'))
            rub = D(node.findtext('Value').replace(',','.')) / nominal
            self.rows.setdefault('RUB',{})[day] = {'rate':str(D(1)/rub),'source':'Bank of Russia official','url':url}
        self.save()

    def download_nbk(self,days):
        """Official NBK dated RSS: USD quote is KZT per quant USD.

        API documentation: https://nationalbank.kz/ru/page/rss
        Cache immutable XML and its source/hash; never use annual audit tax rates.
        """
        from concurrent.futures import ThreadPoolExecutor

        def fetch(day):
            url=f'https://nationalbank.kz/rss/get_rates.cfm?fdate={day:%d.%m.%Y}'
            root=ET.fromstring(self._download(url,f'nbk-rates-{day}.xml'))
            reported=root.findtext('date')
            if not reported:
                raise MissingFX(f'NBK response has no observation date for {day}')
            observed=datetime.strptime(reported.strip(),'%d.%m.%Y').date()
            if observed>day:
                raise MissingFX(f'NBK response {observed} is later than requested {day}')
            usd=next((item for item in root.findall('.//item') if item.findtext('title','').strip()=='USD'),None)
            if usd is None:
                raise MissingFX(f'NBK response has no USD quote for {day}')
            value=D(usd.findtext('description','').strip().replace(',','.'))
            nominal=D(usd.findtext('quant','').strip())
            if value<=0 or nominal<=0:
                raise MissingFX(f'Invalid NBK USD quote for {day}')
            return observed.isoformat(),str(nominal/value),url

        failures=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[(day,pool.submit(fetch,day)) for day in sorted(set(days))]
            for day,future in futures:
                try:
                    observed,rate,url=future.result()
                    self.rows.setdefault('KZT',{})[observed]=dict(rate=rate,source='National Bank of Kazakhstan official',url=url)
                except Exception as exc:
                    failures.append(f'NBK KZT/USD unavailable for {day}: {exc}')
        self.save()
        return failures

    def ensure(self,currencies,start,end,offline=False,required_dates=()):
        errors = []
        if offline:
            return errors
        need = set(currencies)-{'USD'}
        days = set(required_dates)|{start,end}
        # Reuse coverage without network. Missing observations remain explicit.
        ecb_needed = False
        for currency in need-{'KZT'}:
            try:
                for day in days:
                    self.rate(currency,day)
            except MissingFX:
                ecb_needed = True
        if ecb_needed:
            try:
                self.download_ecb()
            except Exception as exc:
                errors.append(f'ECB download unavailable: {exc}')
        if 'RUB' in need:
            try:
                for day in days:
                    self.rate('RUB',day)
            except MissingFX:
                try:
                    self.download_cbr(min(days)-timedelta(days=14),max(days))
                except Exception as exc:
                    errors.append(f'Bank of Russia download unavailable: {exc}')
        if 'KZT' in need:
            missing=[]
            for day in days:
                try:
                    self.rate('KZT',day)
                except MissingFX:
                    missing.append(day)
            if missing:
                errors.extend(self.download_nbk(missing))
        return errors

    def save(self):
        temporary = self.cache_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.rows,sort_keys=True,indent=2),encoding='utf-8')
        temporary.replace(self.cache_file)
        self._index()

    def download_cbr_archive(self, days):
        """Explicit alternate source: cbr-xml-daily.ru republishes CBR fixings.

        Fetch the requested day and follow PreviousURL across closed days. Cache
        raw JSON and provenance; use the response's observation date, never the
        requested date, and never a later fixing.
        """
        from concurrent.futures import ThreadPoolExecutor

        def fetch(day):
            known = self.rows.get('RUB',{}).get(str(day))
            if known and known['source']=='Bank of Russia via cbr-xml-daily.ru archive':
                return str(day),known['rate'],known['url']
            at = day
            for _ in range(16):
                url = f'https://www.cbr-xml-daily.ru/archive/{at:%Y/%m/%d}/daily_json.js'
                path = self.path / f'cbr-mirror-{at}.json'
                if path.exists():
                    raw = path.read_bytes()
                else:
                    try:
                        raw = urlopen(Request(url,headers={'User-Agent':'PortfolioAllocation/1.0'}),timeout=15).read()
                        json.loads(raw)
                        path.write_bytes(raw)
                        path.with_suffix('.json.meta.json').write_text(json.dumps(dict(url=url,
                            retrieved_utc=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest()),indent=2))
                    except Exception:
                        at -= timedelta(days=1)
                        continue
                record = json.loads(raw)
                observed = date.fromisoformat(record['Date'][:10])
                if observed>day:
                    at -= timedelta(days=1)
                    continue
                usd = record['Valute']['USD']
                return observed.isoformat(),str(D(usd['Nominal'])/D(usd['Value'])),url
            raise MissingFX(f'CBR archive unavailable on and before {day}')

        failures = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(day,pool.submit(fetch,day)) for day in sorted(set(days))]
            for day,future in futures:
                try:
                    observed,rate,url = future.result()
                    self.rows.setdefault('RUB',{})[observed] = dict(rate=rate,source='Bank of Russia via cbr-xml-daily.ru archive',url=url)
                except Exception as exc:
                    failures.append(str(exc))
        self.save()
        return failures
