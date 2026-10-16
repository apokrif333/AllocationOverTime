"""Regression coverage for the second broker's real audit schema."""
from copy import deepcopy
import hashlib
from collections import Counter
import pytest
from portfolio_allocation.workbook import Workbook,Instruments
from portfolio_allocation.events import Normalizer
from portfolio_allocation.models import D
from portfolio_allocation.__main__ import run
from .conftest import ROOT


@pytest.fixture(scope='module')
def tsifra():
    wb=Workbook(ROOT/'files/tsifra_1432280_audit.xlsx')
    registry=Instruments(wb)
    return wb,registry,Normalizer(wb,registry,'broker-pl')


def test_actual_tax_transfers_preserve_direction_and_source(tsifra):
    wb,registry,normal=tsifra
    taxes=[e for e in normal.events if e.data.get('cash_role')=='tax']
    assert len(taxes)==22
    assert Counter(e.kind for e in taxes)=={'cash_transfer':22}
    first=next(e for e in taxes if e.amount==D('-37769'))
    assert first.amount==D('-37769') and first.key=='' and first.currency=='RUB'
    refund=next(e for e in taxes if e.amount>0)
    assert refund.amount==3762
    assert sum((e.amount for e in taxes),D())==sum((D(r['Amount']) for r in wb['Transfers'] if r['Transfer_Type']=='tax'),D())
    assert not any('tax' in key.lower() for key in registry.items)


def test_zero_transfer_placeholders_are_unknown_not_free_acquisitions(tsifra):
    wb,_,_=tsifra
    # Keep the old missing-data regression independent of the corrected fixture.
    copied=deepcopy(wb)
    for row in copied['Fifo']:
        if row.get('Enter_Date') and row['Enter_Date']<'2024-02-01':
            row.update(Enter_Date=None,Enter_Amount=0,Enter_Commission=0)
    for row in copied['Transfers']:
        if row['Transfer_Type']=='security':row['Enter_Date']=None
    normal=Normalizer(copied,Instruments(copied))
    transfers=[e for e in normal.events if e.kind=='security_in']
    assert len(transfers)==9
    assert all(e.data['basis'] is None and e.data['basis_status']=='unknown' for e in transfers)
    assert len([i for i in normal.issues if i.code=='transfer_zero_cost_placeholder'])==9


def test_corrected_split_transfers_match_original_acquisition_dates(tsifra):
    wb,_,normal=tsifra
    transfers=[e for e in normal.events if e.kind=='security_in']
    assert len(transfers)==9 and all(e.data['basis_status']=='documented' for e in transfers)
    used=[]
    for e in transfers:
        source=next(row for row in wb['Transfers'] if row['_source']==e.sources[0])
        lots=e.data['basis_lots']
        assert all(lot['acquired']==source['Enter_Date'] for lot in lots)
        assert sum((lot['quantity'] for lot in lots),D())==e.quantity
        assert e.data['basis']>0
        used.extend(e.data['basis_sources'])
    assert len(used)==len(set(used)), 'FIFO acquisition fragments cannot fund two incoming transfers'
    g=[e for e in transfers if e.key=='RU0007288411']
    assert [e.quantity for e in g]==[17,6]
    assert sum((e.data['basis'] for e in g),D())==D('491008.50599991')
    s=[e for e in transfers if e.key=='RU0009029524']
    assert [e.quantity for e in s]==[15000,15000]
    assert s[0].data['basis']!=s[1].data['basis']


def test_income_commission_charged_only_if_excluded_from_net(tsifra):
    wb,_,normal=tsifra
    interest=[e for e in normal.events if e.kind=='income' and e.data['sheet']=='Interest']
    assert len(interest)==4 and all(e.commission==D('.01') for e in interest)
    copied=deepcopy(wb)
    copied['Interest'][0]['Net_Amount']=12.64  # Fee already included in this variant.
    n=Normalizer(copied,Instruments(copied))
    first=next(e for e in n.events if e.kind=='income' and e.sources==['Interest!2'])
    assert first.amount==D('12.64') and first.commission==0


def test_unknown_transfer_type_still_fails_with_record_details(tsifra):
    wb,_,_=tsifra
    copied=deepcopy(wb)
    tax=next(r for r in copied['Transfers'] if r['Transfer_Type']=='tax' and r['Direction']=='out')
    tax['Transfer_Type']='unrecognized'
    with pytest.raises(ValueError,match=tax['_source']+" .*unrecognized.*out"):
        Normalizer(copied,Instruments(copied))


def test_actual_tsifra_cli_outputs_diagnostics_without_modifying_source(tmp_path):
    source=ROOT/'files/tsifra_1432280_audit.xlsx'
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    p,r,n,report,meta=run(source,tmp_path,ROOT/'fx_cache',offline=True,spinoff_policy='broker-pl')
    assert (tmp_path/source.stem/'allocation_dashboard.html').stat().st_size>100
    assert meta['event_count']==502 and meta['state_count']==274
    assert meta['invalid_states']==0 and meta['profit_complete']
    assert not any(row['category'] in ('transfer_zero_cost_placeholder','transfer_basis_unknown','missing_acquisition_fx') for row in report)
    assert p.states[0].quantities['RU0007288411']==23
    assert p.states[0].quantities['RU0009029524']==30000
    assert p.states[0].amounts['RU0007288411']>6000
    assert p.states[0].native_cash.get('RUB',0)==0  # Transfers do not buy securities with cash.
    for state in p.states:
        assert state.valid and abs(sum(state.weights.values())-100)<.000001
    for tax in (e for e in n.events if e.data.get('cash_role')=='tax'):
        postings=[entry for entry in p.cash.entries if entry['sources']==tax.sources]
        assert len(postings)==1 and D(postings[0]['amount'])==tax.amount
    assert p.states[-1].native_cash['RUB']==pytest.approx(694463.12)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
