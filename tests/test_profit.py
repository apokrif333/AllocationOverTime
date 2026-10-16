from datetime import datetime
import pytest
from portfolio_allocation.allocation import Portfolio
from portfolio_allocation.models import D, Instrument
from portfolio_allocation.profit import RealizedProfit
from .conftest import event,ROOT


def replay(events,fx,instruments,**kwargs):
    profit=RealizedProfit(fx,**kwargs)
    portfolio=Portfolio(instruments,fx,profit=profit)
    portfolio.run(events)
    return portfolio,profit


def test_only_closed_fifo_portion_is_realized_net_fees(fx,stock):
    p,r=replay([event(1,'cash_transfer',amount=10000),event(2,quantity=10,amount=100,commission=2),
                event(3,quantity=-4,amount=60,commission=1),event(4,'checkpoint')],fx,{'A':stock})
    assert r.states[0]['cumulative_realized_usd']==0
    assert r.states[1]['cumulative_realized_usd']==0  # Open purchase and fee stay in cost.
    assert r.states[2]['cumulative_realized_usd']==pytest.approx(59-40.8)
    assert r.states[-1]['cumulative_realized_usd']==r.states[2]['cumulative_realized_usd']
    assert p.fifo.basis('A')==D('61.2')


def test_signed_net_income_debit_interest_accrued_coupon_and_refund(fx,stock):
    events=[event(1,'cash_transfer',amount=10000),
            event(2,'income',amount=9,data={'sheet':'Dividends'}),
            event(3,'income',amount=-3,data={'sheet':'Coupons'}),
            event(4,'income',amount=10,data={'sheet':'Coupons'}),
            event(5,'income',amount=-2,data={'sheet':'Interest'}),
            event(6,'cash_transfer',amount='.02',data={'cash_role':'fee_adjustment'})]
    p,r=replay(events,fx,{'A':stock})
    assert r.states[-1]['cumulative_realized_usd']==14.02
    assert r.totals['Dividends']==9 and r.totals['Coupons']==7 and r.totals['Interest']==-2


def test_security_transfers_are_not_profit_and_maturity_uses_imported_basis(fx,stock):
    p,r=replay([event(1,'security_in',quantity=100,data={'basis':D(95),'basis_status':'inferred'}),
                event(2,'security_out',quantity=-20),event(3,'maturity',quantity=-80,amount=80)],fx,{'A':stock})
    assert r.states[0]['cumulative_realized_usd']==0
    assert r.states[1]['cumulative_realized_usd']==0
    assert r.states[-1]['cumulative_realized_usd']==4
    assert r.states[-1]['inferred_count']==1


def test_tax_payments_refunds_and_income_fees_are_not_external_capital(fx):
    events=[event(1,'cash_transfer',key='',amount=1000),
            event(2,'income',key='',amount=100,data={'sheet':'Dividends'}),
            event(3,'cash_transfer',key='',amount=-30,data={'cash_role':'tax'}),
            event(4,'cash_transfer',key='',amount=5,data={'cash_role':'tax'}),
            event(5,'income',key='',amount=10,commission=1,data={'sheet':'Interest'}),
            event(6,'cash_transfer',key='',amount=-200)]
    p,r=replay(events,fx,{})
    assert p.states[-1].native_cash['USD']==884
    assert r.totals['Taxes']==-25
    assert r.totals['Fees / adjustments']==-1
    assert r.states[-1]['cumulative_realized_usd']==84


def test_foreign_tax_payment_is_native_expense_without_synthetic_fx_profit(fx):
    fx.add('EUR','2025-01-02','1.5','fixture')
    p,r=replay([event(1,'cash_transfer',key='',currency='EUR',amount=100),
                event(2,'cash_transfer',key='',currency='EUR',amount=-20,data={'cash_role':'tax'})],fx,{})
    assert r.totals['Taxes']==-30
    assert 'FX realized P/L' not in r.totals
    assert r.native_totals['EUR']['Taxes']==-20
    assert r.states[-1]['cumulative_realized_usd']==-30
    assert p.states[-1].native_cash['EUR']==80


@pytest.mark.parametrize('policy,opening,total',[('closed',0,54),('cash',98,54)])
def test_short_premium_closing_without_double_count(fx,policy,opening,total):
    option=Instrument('P','Put',is_option=True)
    p,r=replay([event(1,key='P',quantity=-2,amount=100,commission=2),
                event(2,key='P',quantity=1,amount=20,commission=1),
                event(3,key='P',quantity=1,amount=22,commission=1)],fx,{'P':option},short_premium_policy=policy)
    assert r.states[0]['cumulative_realized_usd']==opening
    assert r.states[-1]['cumulative_realized_usd']==total
    assert not r.short_lots['P']


def test_long_and_short_expiry_are_realized_only_on_expiration(fx):
    long=Instrument('L','Long option',is_option=True)
    short=Instrument('P','Short option',is_option=True)
    p,r=replay([event(1,key='L',quantity=1,amount=100,commission=1),
                event(2,key='P',quantity=-1,amount=60,commission=2),
                event(3,'option_expiration','L',quantity=-1),
                event(4,'option_expiration','P',quantity=1)],fx,{'L':long,'P':short})
    assert r.states[1]['cumulative_realized_usd']==0
    assert r.states[2]['cumulative_realized_usd']==-101
    assert r.states[-1]['cumulative_realized_usd']==-43


def test_native_trade_profit_is_not_historical_usd_proceeds_minus_cost(fx,stock):
    fx.add('RUB','2025-01-03','.01','fixture')
    p,r=replay([event(1,quantity=10,amount=1000,currency='RUB'),
                event(2,'income',amount=100,currency='RUB',data={'sheet':'Dividends'}),
                event(3,'checkpoint'),event(4,quantity=-5,amount=600,currency='RUB')],fx,{'A':stock})
    assert r.states[1]['cumulative_realized_usd']==2
    assert r.states[2]['cumulative_realized_usd']==2
    # Original RUB basis: 500 RUB; proceeds: 600 RUB. Native profit +100 RUB,
    # plus earlier dividend +100 RUB. Whole accumulated 200 RUB at .01 = $2.
    assert r.native_totals['RUB']['Closed trades']==100
    assert r.states[-1]['native_cumulative']['RUB']==200
    assert r.states[-1]['cumulative_realized_usd']==2


def test_unverified_audit_fx_pnl_is_excluded_and_fee_charged_once(fx):
    fxrow=dict(Operation_Type='fx_trade',Source_Trade_ID='FX1',PnL_Before_Commission=100000,
               Currency='RUB',_source='Fifo!2')
    conversion=event(2,'forex',quantity=-10,price=D(50),commission=1,
                     data={'trade_id':'FX1','base':'USD','quote':'RUB','commission_currency':'USD'})
    p,r=replay([conversion],fx,{},fx_records=[fxrow])
    assert r.states[-1]['cumulative_realized_usd']==-1  # Only fee; purchased RUB remains open.
    assert 'FX realized P/L' not in r.totals
    assert r.totals['Fees / adjustments']==-1
    assert any(i.code=='fx_audit_pnl_excluded' for i in r.issues)


def test_cash_conversion_principal_never_creates_profit(fx):
    fx.add('EUR','2025-01-02','2','fixture')
    events=[event(1,'cash_transfer',currency='EUR',amount=100),event(2,'checkpoint'),
            event(3,'forex',quantity=-40,price=D(2),data={'base':'EUR','quote':'USD','commission_currency':'USD'})]
    p,r=replay(events,fx,{})
    assert r.states[1]['cumulative_realized_usd']==0  # Open EUR +$80 revaluation is excluded.
    assert r.states[-1]['cumulative_realized_usd']==0
    assert not r.entries
    assert p.cash.balances['EUR']==60


def test_actual_currency_borrowing_repayment_realizes_only_settled_debt(fx,stock):
    events=[event(1,quantity=10,currency='RUB',amount=1000),
            event(2,'forex',quantity=-5,price=D(100),data={'base':'USD','quote':'RUB','commission_currency':'USD'}),
            event(3,'checkpoint')]
    p,r=replay(events,fx,{'A':stock})
    assert r.states[0]['cumulative_realized_usd']==0
    assert r.states[1]['cumulative_realized_usd']==5
    assert r.states[2]['cumulative_realized_usd']==5
    assert len(r.entries)==1 and r.entries[0]['category']=='Currency borrowing'
    assert p.cash.balances['RUB']==-500


def test_foreign_income_cumulative_translation_and_actual_fx_fee(fx):
    fx.add('EUR','2025-01-02','1.5','fixture')
    p,r=replay([event(1,'income',amount=100,currency='EUR',data={'sheet':'Dividends'}),
                event(2,'forex',quantity=-50,price=D('1.5'),commission=2,
                      data={'base':'EUR','quote':'USD','commission_currency':'USD'})],fx,{})
    assert r.native_totals['EUR']['Dividends']==100
    assert r.native_totals['USD']['Fees / adjustments']==-2
    assert 'FX realized P/L' not in r.totals
    assert r.states[-1]['cumulative_realized_usd']==148  # Whole 100 EUR * 1.5, less actual USD fee.


def test_unknown_cost_blocks_total_and_preserves_labeled_known_subtotal(fx,stock):
    p,r=replay([event(1,'security_in',quantity=10),event(2,quantity=-5,amount=50),
                event(3,'income',amount=5,data={'sheet':'Dividends'})],fx,{'A':stock})
    assert r.states[-1]['cumulative_realized_usd'] is None
    assert r.states[-1]['known_subtotal_usd']==5
    assert not r.states[-1]['complete']


def test_actual_workbook_realized_profit_cases_and_preserved_allocation():
    from portfolio_allocation.workbook import Workbook,Instruments
    from portfolio_allocation.events import Normalizer
    from portfolio_allocation.fx import FX
    wb=Workbook(ROOT/'files/ib_U5157275_audit.xlsx')
    registry=Instruments(wb)
    normal=Normalizer(wb,registry,'broker-pl')
    rates=FX(ROOT/'fx_cache')
    p,r=replay(normal.events,rates,registry.items,fx_records=wb['Fifo'])
    assert len(r.states)==len(p.states)==428
    assert all(s['complete'] for s in r.states)
    assert r.states[0]['cumulative_realized_usd']==0
    gld=next(k for k,i in registry.items.items() if i.name=='GLD 07FEB25 251 P')
    option_entries=[e for e in r.entries if e['instrument_key']==gld]
    assert len(option_entries)==1
    assert option_entries[0]['timestamp']=='2025-02-03T12:32:07'
    assert option_entries[0]['realized_pnl_native']==pytest.approx(309.8776472)
    redemptions=[e for e in r.entries if e['category']=='Redemptions']
    assert len(redemptions)==22
    assert next(e for e in redemptions if e['instrument_key']=='US912797FS14')['realized_pnl_native']==pytest.approx(8527.3)
    assert r.native_totals['USD']['Dividends']==D('30656.490000000000047')
    assert r.totals['Coupons']==D('21611.87')
    assert r.totals['Corporate actions']==D('61.7103')
    assert r.totals['Fees / adjustments']==D('-1.98')  # FX commission and explicit CAT fee refund.
    assert p.states[-1].native_cash['USD']==pytest.approx(9994.163875393871)
    assert r.states[-1]['native_cumulative']['RUB']==pytest.approx(-415285.03)
    repayments=[e for e in r.entries if e['category']=='Currency borrowing']
    assert sum(e['realized_pnl_native'] for e in repayments if e['timestamp'].startswith('2022-07-28'))==pytest.approx(-18801.233805412943)
    assert all(e['currency']=='USD' for e in repayments)
    assert r.states[-1]['cumulative_realized_usd']==pytest.approx(92551.80658997995)
    assert not any(e['category']=='FX realized P/L' for e in r.entries)
    for state in r.states:
        assert state['known_subtotal_usd']==pytest.approx(sum(state['cumulative_by_category'].values()))
    for before,after in zip(r.states,r.states[1:]):
        if not after['events']:
            assert after['cumulative_realized_usd']==before['cumulative_realized_usd']
