from dataclasses import asdict
import pytest
from portfolio_allocation.models import D
from portfolio_allocation.fx import FX
from portfolio_allocation.allocation import Portfolio
from .conftest import event
from .test_profit import replay


def exchange(day,quantity,price,base='USD',quote='RUB',fee=0):
    return event(day,'forex',quantity=quantity,price=D(price),commission=fee,
                 data={'base':base,'quote':quote,'commission_currency':'USD'})


def test_debt_loss_at_real_repayment_not_at_revaluation_or_spending(fx,stock):
    fx.add('RUB','2025-01-01','.01','fixture')
    fx.add('RUB','2025-01-02','.02','fixture')
    events=[event(1,quantity=10,amount=5000,currency='RUB'),event(2,'checkpoint'),
            exchange(3,-60,50),exchange(4,-40,50),event(5,'checkpoint')]
    p,r=replay(events,fx,{'A':stock})
    assert [s['cumulative_realized_usd'] for s in r.states]==[0,0,-30,-50,-50]
    assert [e['realized_pnl_native'] for e in r.entries]==[-30,-20]
    assert all(e['currency']=='USD' and e['category']=='Currency borrowing' for e in r.entries)
    assert not r.currency_settlements.lots['RUB']
    assert all(row['status']=='pass' for row in r.audit.rows)
    plain=Portfolio({'A':stock},fx);plain.run(events)
    assert [asdict(s) for s in p.states]==[asdict(s) for s in plain.states]


def test_interest_expense_and_loan_fx_loss_are_separate_once(fx,stock):
    fx.add('RUB','2025-01-01','.01','fixture')
    fx.add('RUB','2025-01-02','.02','fixture')
    p,r=replay([event(1,quantity=10,amount=5000,currency='RUB'),
                event(2,'income',amount=-100,currency='RUB',data={'sheet':'Interest'}),
                exchange(3,-102,50,fee=1)],fx,{'A':stock})
    assert r.native_totals['RUB']['Interest']==-100
    assert r.native_totals['USD']['Currency borrowing']==-50
    assert r.native_totals['USD']['Fees / adjustments']==-1
    assert r.states[-1]['cumulative_realized_usd']==-53
    assert all(row['status']=='pass' for row in r.audit.rows)


def test_ordinary_cash_has_no_fictitious_cost_on_spending_or_conversion(fx,stock):
    fx.add('RUB','2025-01-02','.01','fixture')
    p,r=replay([event(1,'cash_transfer',amount=1000,currency='RUB'),
                event(2,quantity=1,amount=500,currency='RUB'),exchange(3,5,100)],fx,{'A':stock})
    assert not r.entries
    assert not r.currency_settlements.audit
    assert p.cash.balances['RUB']==0


@pytest.mark.parametrize('closing_price,expected',[(2,38),('.5',-22)])
def test_actual_currency_round_trip_uses_executions_not_reference_rates(fx,closing_price,expected):
    p,r=replay([event(1,'cash_transfer',amount=200),
                exchange(2,100,1,base='EUR',quote='USD',fee=1),
                exchange(3,-40,closing_price,base='EUR',quote='USD',fee=1)],fx,{})
    assert r.native_totals['USD']['Currency trades']==expected+2
    assert r.states[-1]['cumulative_realized_usd']==expected
    assert r.currency_settlements.lots['EUR'][0].cost==60
    assert p.cash.balances['EUR']==60
    assert all(row['status']=='pass' for row in r.audit.rows)


def test_spending_actual_fx_purchase_does_not_realize_hypothetical_cash_gain(fx,stock):
    p,r=replay([exchange(1,100,1,base='EUR',quote='USD'),
                event(2,quantity=1,amount=60,currency='EUR'),
                exchange(3,-40,2,base='EUR',quote='USD')],fx,{'A':stock})
    assert len(r.entries)==1
    assert r.entries[0]['realized_pnl_native']==40
    assert not r.currency_settlements.lots['EUR']


def test_native_income_reduces_debt_without_a_virtual_usd_cash_trade(fx,stock):
    p,r=replay([event(1,quantity=10,amount=1000,currency='RUB'),
                event(2,'income',amount=500,currency='RUB',data={'sheet':'Coupons'}),
                exchange(3,-5,100)],fx,{'A':stock})
    assert r.native_totals['RUB']['Coupons']==500
    assert r.native_totals['USD']['Currency borrowing']==5
    assert sum(e['category']=='Currency borrowing' for e in r.entries)==1
    assert r.currency_settlements.audit[0]['quantity']=='500'


def test_missing_loan_reference_cost_is_unknown_not_zero(tmp_path,stock):
    fx=FX(tmp_path/'empty')
    p,r=replay([event(1,quantity=1,amount=1000,currency='RUB'),exchange(2,-20,50)],fx,{'A':stock})
    assert r.unknown_count==1
    assert r.entries[0]['realized_pnl_native'] is None
    assert r.states[-1]['cumulative_realized_usd'] is None
    assert any(i.code=='currency_settlement_basis_unknown' for i in r.issues)
