"""Schema-aware read-only extraction with original Excel row references."""
import hashlib
from datetime import date, datetime, time
from pathlib import Path
import re
import openpyxl
from .models import D, Instrument, Issue

REQUIRED = {
    'Trades': {'Date_Time','Trade_ID','Trade_Type','Quantity','Amount','Commission','Currency'},
    'Transfers': {'Date','Transfer_Type','Direction','Amount','Quantity'},
    'CorporateActions': {'Date','Action_Type','Description','Quantity','Proceeds'},
    'Dividends': {'Date','Currency','Net_Amount'},
    'Coupons': {'Date','Currency','Net_Amount'},
    'Interest': {'Date','Currency','Net_Amount'},
    'Fifo': {'Enter_Quantity','Enter_Amount','ISIN'},
    'Positions': {'Date','Quantity','ISIN'},
    'CashBalances': {'Date','Currency','Ending_Cash'},
    'Instruments': {'Symbol','Description','ISIN','Multiplier','Type'},
    'Unprocessed': {'Severity','Reason','Details'},
    'Reconciliation': {'Metric','Severity','Broker_Value','Canonical_Value'},
}


def timestamp(value, default_time=time(0)):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, default_time)
    text = str(value).strip()
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), default_time)
    return datetime.fromisoformat(text)


class Workbook:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.sheets = {}
        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        try:
            for name, required in REQUIRED.items():
                if name not in wb.sheetnames:
                    raise ValueError(f'Missing required sheet: {name}')
                rows = iter(wb[name].values)
                headers = next(rows)
                if not required.issubset(headers):
                    raise ValueError(f'{name}: missing columns {required - set(headers)}')
                self.sheets[name] = [dict(zip(headers, row), _source=f'{name}!{i}', _row=i)
                                     for i,row in enumerate(rows,2) if any(v is not None for v in row)]
        finally:
            wb.close()
        dates = [timestamp(r['Date']).date() for r in self['CashBalances']]
        dates += [timestamp(r['As_Of_Date']).date() for r in self['Instruments'] if r.get('As_Of_Date')]
        event_dates = [timestamp(r['Date_Time']).date() for r in self['Trades']]
        self.end_date = max(dates + event_dates)
        self.issues = []
        if any(timestamp(r['Date']).date() > self.end_date for r in self['Positions']):
            self.issues.append(Issue('warning','forward_position_labels',
                f'Positions has forward year-end labels beyond {self.end_date}; compare against final available state, not future observations.', ['Positions','CashBalances','Instruments']))

    def __getitem__(self, name):
        return self.sheets[name]


class Instruments:
    def __init__(self, wb):
        self.items = {}
        self.metadata = wb['Instruments']
        self.issues = []

    def resolve(self, row, override_isin=None):
        isin = override_isin if override_isin is not None else row.get('ISIN')
        symbol = row.get('Symbol') or isin or 'Unknown'
        matches = [m for m in self.metadata if (isin and m.get('ISIN') == isin) or
                   (not isin and symbol in (m.get('Symbol'),m.get('Description')))]
        meta = matches[-1] if matches else {}
        name = meta.get('Description') or symbol
        kind = str(row.get('Asset_Type') or '')
        is_option = 'Option' in kind or meta.get('Type') in ('C','P')
        mult = D(row.get('Multiplier') or meta.get('Multiplier') or 1)
        strike = D(meta['Strike']) if meta.get('Strike') is not None else None
        expiry = str(meta.get('Expiry') or '')
        opt_type = meta.get('Type') if is_option else ''
        if is_option and strike is None:
            match = re.search(r'(\d{2}[A-Z]{3}\d{2})\s+([\d.]+)\s+([CP])$', symbol)
            if match:
                expiry = datetime.strptime(match[1],'%d%b%y').date().isoformat()
                strike = D(match[2])
                opt_type = match[3]
        if isin:
            key = isin
        elif is_option:
            identity = '|'.join(map(str,[name,expiry,strike,opt_type,mult,meta.get('Underlying') or '',kind]))
            key = 'OPTION:' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        else:
            key = 'CONTRACT:' + str(meta.get('Conid') or symbol)
        if key not in self.items:
            asset_class = 'Other'
            if is_option:
                asset_class = 'Long options'
            elif kind == 'Treasury Bills' or (kind=='Bonds' and 'TREASURY BILL' in str(meta.get('Description') or '').upper()):
                asset_class = 'Treasury bills'
            elif meta.get('Type') == 'Govt' or (kind=='Bonds' and 'TSY INFL IX' in str(meta.get('Description') or '').upper()):
                asset_class = 'Government bonds'
            elif meta.get('Type') == 'Corp' or kind == 'Bonds':
                asset_class = 'Corporate bonds'
            elif kind == 'Stocks' or meta.get('Type') in ('COMMON','ETF','ADR','GDR','PREFERENCE'):
                asset_class = 'Stocks / ETFs'
            self.items[key] = Instrument(key,name,symbol,isin or '',asset_class,
                row.get('Currency') or 'USD',mult,strike,opt_type or '',expiry,
                meta.get('Underlying') or '',is_option,'Futures' in kind)
        return key
