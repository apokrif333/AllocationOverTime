from collections import Counter
import pytest
from portfolio_allocation.workbook import Workbook,Instruments
from portfolio_allocation.events import Normalizer
from portfolio_allocation.fx import FX
from portfolio_allocation.models import D
from portfolio_allocation.profit_audit import source_coverage,fifo_comparison
from .conftest import ROOT
from .test_profit import replay


@pytest.mark.parametrize('filename,rows,checks',[
    ('ib_U5157275_audit.xlsx',613,796),
    ('tsifra_1432280_audit.xlsx',499,502),
    ('halyk_1028197847_audit.xlsx',57,81)])
def test_all_source_operations_and_native_cash_basis_bridge(filename,rows,checks):
    wb=Workbook(ROOT/'files'/filename);registry=Instruments(wb)
    normal=Normalizer(wb,registry,'broker-pl');fx=FX(ROOT/'fx_cache')
    p,r=replay(normal.events,fx,registry.items,fx_records=wb['Fifo'])
    coverage=source_coverage(wb,normal)
    assert len(coverage)==rows
    assert all(x['status']=='linked' for x in coverage)
    assert len(r.audit.rows)==checks
    assert all(x['status']=='pass' for x in r.audit.rows)
    comparisons=fifo_comparison(wb,normal,r)
    assert not any(x['status'] in ('error','unavailable') for x in comparisons)
    assert sum((D(x['difference']) for x in comparisons if x['status']=='explained_spinoff'),D())==pytest.approx(0,abs=1e-8)
    if filename.startswith('ib_'):
        assert Counter(x['status'] for x in comparisons)=={'pass':67,'explained_spinoff':2}
        repayments=[x for x in r.currency_settlements.audit if x['timestamp'].startswith('2022-07-28')]
        assert sum((D(x['historical_basis']) for x in repayments),D())==pytest.approx(D('64380.91606975706'))
        assert sum((D(x['settlement_amount']) for x in repayments),D())==pytest.approx(D('83182.14987517'))
    else:
        assert not r.currency_settlements.audit
