"""Halyk aliases, supplementary redemption records and official KZT rates."""
from copy import deepcopy
from datetime import date,datetime
import hashlib
import shutil
import subprocess
from collections import defaultdict
import pytest
from portfolio_allocation.__main__ import run
from portfolio_allocation.allocation import Portfolio
from portfolio_allocation.events import Normalizer
from portfolio_allocation.fx import FX
from portfolio_allocation.models import D
from portfolio_allocation.profit import RealizedProfit
from portfolio_allocation.workbook import Workbook,Instruments
from .conftest import ROOT


@pytest.fixture(scope='module')
def halyk():
    wb=Workbook(ROOT/'files/halyk_1028197847_audit.xlsx')
    registry=Instruments(wb)
    normal=Normalizer(wb,registry,'broker-pl')
    fx=FX(ROOT/'fx_cache')
    profit=RealizedProfit(fx,wb['Fifo'])
    portfolio=Portfolio(registry.items,fx,profit=profit)
    portfolio.run(normal.events)
    return wb,registry,normal,portfolio,profit


def test_actual_redemptions_close_once_and_keep_trade_fees(halyk):
    wb,registry,normal,p,profit=halyk
    events=[e for e in normal.events if e.data.get('trade_type')=='redemption']
    assert len(events)==10 and all(e.kind=='maturity' and len(e.sources)==2 for e in events)
    assert len([e for e in normal.events if e.kind=='maturity'])==10
    assert not any(i.code=='uncovered_security_short' for i in p.issues)
    for e in events:
        state=next(s for s in p.states if s.timestamp==e.timestamp)
        assert state.quantities[e.key]==0 and state.amounts[e.key]==0
        postings=[entry for entry in p.cash.entries if entry['sources']==e.sources]
        assert len(postings)==1 and D(postings[0]['amount'])==e.amount-e.commission
        entries=[entry for entry in profit.entries if entry['sources']=='; '.join(e.sources)]
        assert len(entries)==1 and entries[0]['category']=='Redemptions'
    first=next(e for e in events if e.key=='US912797FH58')
    pl=next(e['realized_pnl_native'] for e in profit.entries if e['instrument_key']==first.key)
    assert pl==pytest.approx(102000-14.06923142467621-99739.17-114.7865486182639)


def test_standalone_redemption_without_supplementary_sheet_still_works(halyk):
    wb,_,_,_,_=halyk
    copied=deepcopy(wb)
    copied.sheets['CorporateActions']=[]
    registry=Instruments(copied)
    normal=Normalizer(copied,registry)
    profit=RealizedProfit(FX(ROOT/'fx_cache'),copied['Fifo'])
    p=Portfolio(registry.items,profit.fx,profit=profit)
    p.run(normal.events)
    assert len([e for e in normal.events if e.kind=='redemption'])==10
    assert len([e for e in profit.entries if e['category']=='Redemptions'])==10
    assert not any(i.code=='uncovered_security_short' for i in p.issues)


def test_disagreeing_redemption_is_flagged_without_second_cash_payment(halyk):
    wb,_,_,_,_=halyk
    copied=deepcopy(wb)
    copied['CorporateActions'][0]['Proceeds']+=1
    normal=Normalizer(copied,Instruments(copied))
    assert any(i.code=='ambiguous_redemption_duplicate' for i in normal.issues)
    assert len([e for e in normal.events if e.key=='US912797FH58' and e.kind in ('maturity','redemption')])==1


def test_metadata_classes_positions_and_daily_kzt_basis(halyk):
    wb,registry,normal,p,profit=halyk
    assert all(s.valid for s in p.states)
    assert all(q>=0 for state in p.states for q in state.quantities.values())
    assert all(abs(sum(s.weights.values())-100)<.000001 for s in p.states)
    assert registry.items['US912797FH58'].asset_class=='Treasury bills'
    assert registry.items['US912828V491'].asset_class=='Government bonds'
    assert registry.items['KZ2D00015328'].asset_class=='Corporate bonds'
    assert registry.items['IE00BGSF1X88'].asset_class=='Stocks / ETFs'
    purchase=next(e for e in normal.events if e.key=='KZ2D00015328' and e.quantity>0)
    state=next(s for s in p.states if s.timestamp==purchase.timestamp)
    assert state.amounts[purchase.key]==pytest.approx(float(profit.fx.usd(D(9073628),'KZT',purchase.timestamp)))
    assert state.amounts[purchase.key]!=9073628
    assert p.states[-1].quantities['KZ2D00015328']==3697000
    rate,record=profit.fx.rate('KZT',date(2026,10,9))
    assert 0<rate<D('.01') and record['rate_date']=='2026-10-09'
    assert record['source']=='National Bank of Kazakhstan official'


def test_nbk_parser_uses_quote_nominal_and_rejects_future_observation(tmp_path,monkeypatch):
    fx=FX(tmp_path/'rates')
    raw=b'<rates><date>09.10.2026</date><item><title>USD</title><description>5000</description><quant>10</quant></item></rates>'
    monkeypatch.setattr(fx,'_download',lambda url,name:raw)
    assert fx.download_nbk({date(2026,10,9)})==[]
    assert fx.rate('KZT',date(2026,10,9))[0]==D('.002')
    bad=FX(tmp_path/'future')
    monkeypatch.setattr(bad,'_download',lambda url,name:raw)
    assert bad.download_nbk({date(2026,10,8)})
    assert not bad.rows.get('KZT')


def test_nbk_offline_does_not_download(fx,monkeypatch):
    monkeypatch.setattr(fx,'download_nbk',lambda days:pytest.fail('Network call in offline mode'))
    assert fx.ensure({'KZT'},date(2026,10,9),date(2026,10,9),offline=True)==[]


def test_actual_halyk_outputs_expose_missing_funding_without_fake_adjustments(tmp_path):
    source=ROOT/'files/halyk_1028197847_audit.xlsx'
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    p,r,n,report,meta=run(source,tmp_path,ROOT/'fx_cache',offline=True,spinoff_policy='broker-pl')
    assert meta['event_count']==51 and meta['state_count']==meta['valid_states']==36
    assert not p.issues
    assert any(row['category']=='cash_funding_history_missing' for row in report)
    assert len([row for row in report if row['category']=='cash_balance' and row['severity']=='blocking'])==2
    assert not any(e['kind']=='cash_transfer' for e in p.event_audit)
    assert p.states[-1].native_cash['USD']==pytest.approx(-397584.10886086405)
    assert p.states[-1].native_cash['KZT']==pytest.approx(-1792910.42)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    if shutil.which('node') and (ROOT/'.qa/node_modules/jsdom').exists():
        result=subprocess.run(['node',str(ROOT/'tools/verify_plotly_render.cjs'),
                               str(tmp_path/source.stem/'allocation_dashboard.html')],
                              capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
