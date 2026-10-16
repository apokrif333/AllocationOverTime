"""Populate a documented cache; run once online, then use --offline."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import sys
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio_allocation.fx import FX

# Fetch independently, then parse sequentially to avoid competing cache writes.
def fetch(pair):
    name,url = pair
    try:
        raw = urlopen(url,timeout=25).read()
        print(name,len(raw),raw[:60],flush=True)
        return name,url,raw
    except Exception as exc:
        print(name,type(exc).__name__,str(exc),flush=True)
        return name,url,None

if __name__=='__main__':
    urls = [
        ('ecb','https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml'),
        ('cbr','https://cbr.ru/scripts/XML_dynamic.asp?date_req1=01/11/2021&date_req2=08/10/2026&VAL_NM_RQ=R01235'),
        ('cbrwww','https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=01/11/2021&date_req2=08/10/2026&VAL_NM_RQ=R01235'),
    ]
    import hashlib,json,xml.etree.ElementTree as ET
    from datetime import datetime,timezone
    fx = FX('fx_cache')
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch,urls))
    for name,url,raw in results:
        if raw is None:
            continue
        ET.fromstring(raw)
        filename = 'ecb-eurofxref-hist.xml' if name=='ecb' else 'cbr-usd-2021-11-01-2026-10-08.xml'
        path = fx.path/filename
        path.write_bytes(raw)
        path.with_suffix('.xml.meta.json').write_text(json.dumps(dict(url=url,retrieved_utc=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest()),indent=2))
    if (fx.path/'ecb-eurofxref-hist.xml').exists():
        fx.download_ecb()
    if (fx.path/'cbr-usd-2021-11-01-2026-10-08.xml').exists():
        fx.download_cbr(date(2021,11,1),date(2026,10,8))
    print({c:(min(r),max(r),len(r)) for c,r in fx.rows.items() if c in ('RUB','EUR')})
