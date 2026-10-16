from datetime import datetime
from pathlib import Path
import pytest
from portfolio_allocation.models import D, Instrument, Event
from portfolio_allocation.fx import FX

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def fx(tmp_path):
    rates=FX(tmp_path/'fx')
    for currency,rate in [('EUR','1.2'),('RUB','.02')]:
        rates.add(currency,'2025-01-01',rate,'unit-test fixture')
    return rates


@pytest.fixture
def stock():
    return Instrument('A','Company A','AAA','US0000000001','Stocks / ETFs')


def event(day,kind='trade',key='A',quantity=0,amount=0,commission=0,currency='USD',**kwargs):
    return Event(datetime(2025,1,day,12),kind,key,currency,D(quantity),D(amount),D(commission),
                 sources=[f'fixture!{day}'],**kwargs)
