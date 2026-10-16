from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio_allocation.workbook import Workbook, Instruments
from portfolio_allocation.events import Normalizer
from portfolio_allocation.fx import FX, MissingFX

if __name__=='__main__':
    wb=Workbook('files/ib_U5157275_audit.xlsx')
    normal=Normalizer(wb,Instruments(wb))
    fx=FX('fx_cache')
    days=[]
    for day in sorted({e.timestamp.date() for e in normal.events}):
        if day.isoformat()>'2022-03-01':
            # ECB stopped publishing RUB. Prefer an actual CBR fixing even when
            # the old ECB observation would still pass a staleness threshold.
            days.append(day)
            continue
        try:
            fx.rate('RUB',day)
        except MissingFX:
            days.append(day)
    print(f'Fetch {len(days)} missing event-date RUB observations',flush=True)
    failures=fx.download_cbr_archive(days)
    print('Failures:',failures,flush=True)
