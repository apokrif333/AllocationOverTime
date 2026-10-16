from datetime import datetime
from decimal import Decimal
import pytest
from portfolio_allocation.allocation import Portfolio
from portfolio_allocation.models import D, Instrument
from portfolio_allocation.fx import MissingFX
from portfolio_allocation.colors import palette, CASH_COLOR
from portfolio_allocation.visualization import filtered_values
from .conftest import event


def test_fifo_fractional_purchases_partial_sale_and_liquidation(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,quantity='2.5',amount=100,commission=1),
           event(3,quantity='1.5',amount=90,commission=2),event(4,quantity=-3,amount=180,commission=3),
           event(5,quantity=-1,amount=20,commission=1)])
    assert p.states[2].amounts['A']==193
    assert p.states[3].amounts['A']==pytest.approx(92*1/1.5)
    assert p.states[-1].amounts['A']==0
    assert p.cash.balances['USD']==D(1000)-101-92+177+19


@pytest.mark.parametrize('proceeds',[50,150])
def test_sale_profit_or_loss_changes_cash_not_historical_basis(fx,stock,proceeds):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,quantity=10,amount=100,commission=2),
           event(3,quantity=-5,amount=proceeds,commission=3)])
    assert p.fifo.basis('A')==51
    assert p.cash.balances['USD']==D(1000)-102+D(proceeds)-3


def test_security_transfers_no_cash_or_realized_sale(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=500),event(2,'security_in',quantity=10,data={'basis':D(200),'basis_status':'inferred'}),
           event(3,'security_out',quantity=-4)])
    assert p.fifo.quantity('A')==6
    assert p.fifo.basis('A')==120
    assert p.cash.balances['USD']==500
    assert not any(e['kind']=='security_out' for e in p.cash.entries)


def test_transferred_lots_fifo_uses_purchase_dates_not_transfer_row_order():
    from portfolio_allocation.fifo import FIFO
    fifo=FIFO()
    fifo.add('A',2,200,datetime(2022,1,25),'newer purchase')
    fifo.add('A',2,100,datetime(2021,11,23),'older purchase')
    removed,missing=fifo.remove('A',D('2.5'))
    assert missing==0
    assert [lot.source for lot in removed]==['older purchase','newer purchase']
    assert sum((lot.cost_usd for lot in removed),D())==150
    assert fifo.basis('A')==150


def test_fx_online_coverage_checks_internal_dates_and_offline_never_downloads(fx,monkeypatch):
    from datetime import date
    fx.add('RUB','2025-03-01','.01','fixture')
    calls=[]
    monkeypatch.setattr(fx,'download_ecb',lambda: calls.append('ECB'))
    monkeypatch.setattr(fx,'download_cbr',lambda start,end: calls.append((start,end)))
    start,end=date(2025,1,1),date(2025,3,1)
    gap=date(2025,2,1)
    assert fx.ensure({'RUB'},start,end,offline=True,required_dates={gap})==[]
    assert calls==[]
    fx.ensure({'RUB'},start,end,required_dates={gap})
    assert (date(2024,12,18),end) in calls


def test_maturity_cash_and_cost_once(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,quantity=100,amount=95,commission=1),
           event(3,'maturity',quantity=-100,amount=100)])
    assert p.fifo.basis('A')==0
    assert p.cash.balances['USD']==1004


def test_short_put_premium_collateral_partial_close_expiration(fx):
    option=Instrument('PUT','Test put',asset_class='Long options',multiplier=D(100),strike=D(25),option_type='P',is_option=True)
    p=Portfolio({'PUT':option},fx)
    p.run([event(1,'cash_transfer',amount=10000),event(2,key='PUT',quantity=-2,amount=600,commission=2),
           event(3,key='PUT',quantity=1,amount=25,commission=1),event(4,'option_expiration','PUT',quantity=1)])
    opened=p.states[1]
    assert opened.amounts['PUT']==5000
    assert opened.total_cash==10598
    assert opened.free_cash==5598
    assert opened.denominator==10598
    assert p.states[2].reserved==2500
    assert p.states[-1].reserved==0
    assert p.states[-1].amounts['PUT']==0
    assert p.states[-1].total_cash==10572


def test_insufficient_short_collateral_never_manufactures_cash(fx):
    option=Instrument('PUT','Put',multiplier=D(100),strike=D(25),option_type='P',is_option=True)
    p=Portfolio({'PUT':option},fx)
    p.run([event(1,'cash_transfer',amount=100),event(2,key='PUT',quantity=-1,amount=50)])
    assert p.states[-1].reserved==150
    assert p.states[-1].free_cash==0
    assert p.states[-1].denominator==150
    assert any('Insufficient cash' in w for w in p.states[-1].warnings)


def test_long_option_expiration_releases_cost_without_cash(fx):
    option=Instrument('OPT','Long option',is_option=True)
    p=Portfolio({'OPT':option},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,key='OPT',quantity=1,amount=100,commission=1),
           event(3,'option_expiration','OPT',quantity=-1)])
    assert p.states[1].amounts['OPT']==101
    assert p.states[-1].amounts['OPT']==0
    assert p.states[-1].total_cash==899


def test_fx_signed_legs_native_cash_and_historical_cost(fx,stock):
    p=Portfolio({'A':stock},fx)
    fx.add('RUB','2025-01-04','.01','unit-test fixture')
    p.run([event(1,'cash_transfer',amount=1000),
           event(2,'forex',quantity=-100,commission=2,price=D(50),data={'base':'USD','quote':'RUB','commission_currency':'USD'}),
           event(3,quantity=10,amount=1000,commission=10,currency='RUB'),event(4,'checkpoint')])
    assert p.cash.balances['USD']==898
    assert p.cash.balances['RUB']==3990
    assert p.states[2].amounts['A']==20.2
    assert p.states[3].amounts['A']==20.2
    assert p.states[3].total_cash==937.9


def test_income_and_fees_are_signed_net_cash(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=100),event(2,'income',amount=8),
           event(3,'income',amount=-5),event(4,'income',amount=10),event(5,'income',amount=-2)])
    assert p.cash.balances['USD']==111


def test_borrowing_is_visible_not_negative_area(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=100),event(2,quantity=10,amount=200)])
    s=p.states[-1]
    assert s.total_cash==-100 and s.free_cash==-100
    assert s.borrowing==100
    assert s.amounts['Cash']==0 and s.denominator==200 and s.net_capital==100
    assert s.weights['A']==100
    assert any('positive gross capital' in w for w in s.warnings)


def test_unknown_transfer_basis_stays_unavailable(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,'security_in',quantity=10)])
    assert p.states[-1].amounts['A'] is None
    assert p.states[-1].weights['Cash'] is None
    assert not p.states[-1].valid


def test_missing_fx_never_defaults_to_one(fx):
    with pytest.raises(MissingFX):
        fx.rate('CHF',datetime(2025,1,1))
    with pytest.raises(MissingFX):
        fx.rate('RUB',datetime(2025,3,1))
    assert fx.rate('EUR',datetime(2025,1,4))[1]['rate_date']=='2025-01-01'


def test_filter_keeps_full_denominator(fx,stock):
    p=Portfolio({'A':stock},fx)
    p.run([event(1,'cash_transfer',amount=1000),event(2,quantity=10,amount=200)])
    s=p.states[-1]
    assert filtered_values(s,['A'])=={'A':20}
    assert s.denominator==1000
    assert sum(s.weights.values())==100


def test_unique_stable_perceptual_colors_and_persistence(tmp_path):
    keys=['ISIN:'+str(i) for i in range(100)]+['Cash']
    first=palette(keys,tmp_path/'colors.json')
    assert first==palette(list(reversed(keys)),tmp_path/'colors.json')
    assert first==palette(keys)
    assert len(set(first.values()))==len(keys)
    assert first['Cash']==CASH_COLOR
    assert palette(['new']+keys,tmp_path/'colors.json') | first == palette(['new']+keys,tmp_path/'colors.json')


def test_corporate_conversion_conserves_fifo_basis(fx,stock):
    other=Instrument('B','Successor')
    p=Portfolio({'A':stock,'B':other},fx)
    p.run([event(1,quantity=10,amount=100),event(2,'conversion',quantity=10,data={'target':'B','ratio':D(2)})])
    assert p.fifo.quantity('A')==0
    assert p.fifo.quantity('B')==20
    assert p.fifo.basis('B')==100
