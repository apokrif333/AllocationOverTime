"""Native realized money and whole-cumulative display conversion regressions."""
from datetime import datetime
from dataclasses import asdict
import pytest
from portfolio_allocation.models import D,Instrument
from portfolio_allocation.allocation import Portfolio
from portfolio_allocation.fx import FX
from portfolio_allocation.profit import RealizedProfit
from portfolio_allocation.workbook import Workbook,Instruments,timestamp
from portfolio_allocation.events import Normalizer
from .conftest import ROOT,event
from .test_profit import replay


@pytest.mark.parametrize('currency,opening_rate,closing_rate',[('RUB','.02','.01'),('KZT','.004','.002')])
def test_trade_profit_uses_native_fifo_not_different_fx_dates(fx,stock,currency,opening_rate,closing_rate):
    fx.add(currency,'2025-01-01',opening_rate,'fixture')
    fx.add(currency,'2025-01-03',closing_rate,'fixture')
    events=[event(1,quantity='2.5',amount=1000,commission=10,currency=currency),
            event(3,quantity=-1,amount=500,commission=5,currency=currency)]
    p,r=replay(events,fx,{'A':stock})
    expected=D(495)-D(1010)/D('2.5')
    assert r.states[-1]['native_cumulative'][currency]==float(expected)
    assert r.states[-1]['by_currency'][currency]['cumulative_realized']==float(expected)
    assert r.states[-1]['cumulative_realized_usd']==float(expected*D(closing_rate))
    # Allocation retains the original historical USD basis for remaining units.
    assert p.states[-1].amounts['A']==float(D(1010)*D(opening_rate)*D('1.5')/D('2.5'))
    plain=Portfolio({'A':stock},fx);plain.run(events)
    assert [asdict(s) for s in plain.states]==[asdict(s) for s in p.states]


def test_whole_accumulated_native_curve_is_retranslated_only_at_profit_events(fx):
    for day,rate in [(1,'.02'),(2,'.01'),(3,'.03'),(4,'.04')]:fx.add('RUB',f'2025-01-{day:02}',rate,'fixture')
    p,r=replay([event(1,'income',amount=100,currency='RUB',data={'sheet':'Dividends'}),
                event(2,'income',amount=100,currency='RUB',data={'sheet':'Dividends'}),
                event(3,'cash_transfer',amount=10000,currency='RUB'),
                event(4,'income',amount=-20,currency='RUB',data={'sheet':'Interest'})],fx,{})
    assert r.default_currency=='RUB'
    assert [s['native_cumulative']['RUB'] for s in r.states]==[100,200,200,180]
    assert [s['cumulative_realized_usd'] for s in r.states]==[2,2,2,7.2]
    assert r.states[2]['valuation_timestamp']==r.states[1]['valuation_timestamp']
    assert not r.states[2]['is_profit_event']
    assert len(r.entries)==3 and all(e['currency']=='RUB' for e in r.entries)


def test_missing_display_rate_does_not_destroy_native_profit(tmp_path):
    fx=FX(tmp_path/'empty-cache')
    p,r=replay([event(1,quantity=10,amount=100,currency='KZT'),
                event(2,quantity=-10,amount=130,currency='KZT')],fx,{'A':Instrument('A','Native KZT security',currency='KZT')})
    assert r.unknown_count==0
    assert r.states[-1]['by_currency']['KZT']['cumulative_realized']==30
    assert r.states[-1]['by_currency']['KZT']['complete']
    assert r.states[-1]['by_currency']['USD']['cumulative_realized'] is None
    assert not r.states[-1]['by_currency']['USD']['complete']
    assert any(i.code=='missing_profit_display_fx' for i in r.issues)


def test_mixed_currency_totals_use_one_event_date_and_cross_rates(fx):
    fx.add('RUB','2025-01-01','.01','fixture')
    fx.add('KZT','2025-01-01','.002','fixture')
    p,r=replay([event(1,'income',amount=10,data={'sheet':'Dividends'}),
                event(2,'income',amount=1000,currency='RUB',data={'sheet':'Coupons'}),
                event(3,'income',amount=5000,currency='KZT',data={'sheet':'Interest'})],fx,{})
    s=r.states[-1]
    assert s['native_cumulative']=={'USD':10,'RUB':1000,'KZT':5000}
    assert s['by_currency']['USD']['cumulative_realized']==30
    assert s['by_currency']['RUB']['cumulative_realized']==3000
    assert s['by_currency']['KZT']['cumulative_realized']==15000
    assert s['by_currency']['RUB']['categories']['Interest']==1000


def test_transferred_native_basis_uses_original_cost_without_conversion(fx,stock):
    p,r=replay([event(1,'security_in',quantity=10,currency='RUB',data={'basis':D(1000),'basis_status':'documented'}),
                event(2,'security_out',quantity=-4,currency='RUB'),
                event(3,quantity=-6,amount=900,commission=1,currency='RUB')],fx,{'A':stock})
    assert r.states[-1]['native_cumulative']['RUB']==299
    assert p.states[0].native_cash.get('RUB',0)==0
    assert p.states[1].native_cash.get('RUB',0)==0


def test_native_short_premium_and_closing_payment_do_not_use_opening_fx(fx):
    fx.add('RUB','2025-01-02','.01','fixture')
    p,r=replay([event(1,key='P',quantity=-1,amount=100,commission=2,currency='RUB'),
                event(2,key='P',quantity=1,amount=20,commission=1,currency='RUB')],fx,{'P':Instrument('P','Put',currency='RUB',is_option=True)})
    assert r.states[0]['cumulative_realized_usd']==0
    assert r.states[-1]['native_cumulative']['RUB']==77
    assert r.states[-1]['cumulative_realized_usd']==.77


@pytest.mark.parametrize('filename,expected_currency',[('tsifra_1432280_audit.xlsx','RUB'),('halyk_1028197847_audit.xlsx','USD')])
def test_actual_brokers_native_profit_and_event_date_usd_conversion(filename,expected_currency):
    wb=Workbook(ROOT/'files'/filename);registry=Instruments(wb)
    normal=Normalizer(wb,registry,'broker-pl');fx=FX(ROOT/'fx_cache')
    p,r=replay(normal.events,fx,registry.items,fx_records=wb['Fifo'])
    last=r.states[-1]
    assert r.default_currency==expected_currency
    assert all(s['by_currency'][expected_currency]['complete'] for s in r.states)
    assert not any(e['category']=='FX realized P/L' for e in r.entries)
    at=timestamp(last['valuation_timestamp'])
    expected=sum((fx.usd(D(v),c,at) for c,v in last['native_cumulative'].items()),D())
    assert last['cumulative_realized_usd']==pytest.approx(float(expected))
    if expected_currency=='RUB':
        # Independent native tax-audit bridge; small source lot-rounding only.
        native=sum((D(row['PnL_After_All_Commissions']) for row in wb['Fifo']),D())
        native+=sum((D(row['Net_Amount']) for name in ('Dividends','Coupons','Interest') for row in wb[name]),D())
        native+=sum((D(row['Amount']) for row in wb['Transfers'] if row['Transfer_Type']=='tax'),D())
        native-=sum((D(row.get('Commission')) for row in wb['Interest']),D())
        assert last['native_cumulative']['RUB']==pytest.approx(float(native),abs=.01)
        assert last['native_cumulative']['RUB']==pytest.approx(1798096.92854959)
    else:
        assert last['native_cumulative']['KZT']==pytest.approx(1905568.38)
        assert last['native_cumulative']['USD']==pytest.approx(20068.53581522253)
