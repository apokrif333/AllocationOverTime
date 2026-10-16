"""Rebuild RUB observations from validated local archive responses, no network."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio_allocation.fx import FX
from portfolio_allocation.models import D

if __name__=='__main__':
    fx=FX('fx_cache')
    count=0
    for path in sorted(fx.path.glob('cbr-mirror-*.json')):
        if path.name.endswith('.meta.json'):
            continue
        raw=path.read_bytes()
        provenance=json.loads(path.with_suffix('.json.meta.json').read_text(encoding='utf-8'))
        if hashlib.sha256(raw).hexdigest()!=provenance['sha256']:
            raise ValueError(f'Cached response hash mismatch: {path.name}')
        data=json.loads(raw)
        day=data['Date'][:10]
        usd=data['Valute']['USD']
        rate=D(usd['Nominal'])/D(usd['Value'])
        fx.rows.setdefault('RUB',{})[day]=dict(rate=str(rate),source='Bank of Russia via cbr-xml-daily.ru archive',url=provenance['url'])
        count+=1
    fx.save()
    print(f'Imported {count} cached responses with verified hashes, no network')
