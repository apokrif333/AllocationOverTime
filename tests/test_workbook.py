from copy import deepcopy
from datetime import datetime
import hashlib
import pytest
from portfolio_allocation.workbook import Workbook,Instruments
from portfolio_allocation.events import Normalizer
from portfolio_allocation.fx import FX
from portfolio_allocation.allocation import Portfolio
from portfolio_allocation.reconciliation import reconcile
from .conftest import ROOT


@pytest.fixture(scope='module')
def integrated():
    wb=Workbook(ROOT/'files/ib_U5157275_audit.xlsx')
    registry=Instruments(wb)
    normal=Normalizer(wb,registry,'broker-pl')
    portfolio=Portfolio(registry.items,FX(ROOT/'fx_cache'))
    portfolio.run(normal.events)
    return wb,registry,normal,portfolio


def test_input_schema_hash_and_initial_cash(integrated):
    wb,registry,normal,p=integrated
    assert wb.sha256=='c6ebe8e68d5c9687307aa28b0d0a0582288ff2f36b830c878fbe2969e67a85ec'
    assert len(wb['Trades'])==196
    assert p.states[0].timestamp.date().isoformat()=='2021-11-22'
    assert p.states[0].total_cash==100000
    assert p.states[0].weights['Cash']==100
    assert p.states[-1].timestamp.date().isoformat()=='2026-10-08'
    assert hashlib.sha256(wb.path.read_bytes()).hexdigest()==wb.sha256


def test_real_treasury_transfer_no_cash_and_original_basis(integrated):
    wb,r,n,p=integrated
    key='US912797FS14'
    state=next(s for s in p.states if s.timestamp.date().isoformat()=='2023-10-23')
    prior=p.states[p.states.index(state)-1]
    assert state.amounts[key]==191472.7  # Corrected source acquisition amount.
    assert state.basis_status[key]=='documented'
    assert state.quantities[key]==200000
    assert state.native_cash==prior.native_cash


def test_real_maturities_deduplicated_semantically(integrated):
    wb,r,n,p=integrated
    redemptions=[e for e in n.events if e.kind in ('maturity','full_call')]
    assert len(redemptions)==22
    assert all(len(e.sources)==2 for e in redemptions)
    event=next(e for e in redemptions if e.key=='US912797FS14')
    state=next(s for s in p.states if s.timestamp==event.timestamp)
    before=p.states[p.states.index(state)-1]
    assert state.amounts[event.key]==0
    assert state.native_cash['USD']-before.native_cash['USD']==pytest.approx(200000)


def test_real_gld_put_lifetime_and_cash(integrated):
    wb,r,n,p=integrated
    key=next(k for k,i in r.items.items() if i.name=='GLD 07FEB25 251 P')
    opened=next(s for s in p.states if s.timestamp==datetime(2025,1,16,12,38,12))
    closed=next(s for s in p.states if s.timestamp==datetime(2025,2,3,12,32,7))
    prior=p.states[p.states.index(opened)-1]
    before_close=p.states[p.states.index(closed)-1]
    assert opened.amounts[key]==25100
    assert opened.total_cash-prior.total_cash==pytest.approx(326-1.0671028)
    assert closed.amounts[key]==0 and closed.reserved==0
    assert closed.total_cash-before_close.total_cash==pytest.approx(-14-1.05525)
    assert all(s.amounts.get(key,0)==0 for s in p.states if s.timestamp>closed.timestamp)


def test_real_long_options_expire(integrated):
    wb,r,n,p=integrated
    for e in (e for e in n.events if e.kind=='option_expiration'):
        state=next(s for s in p.states if s.timestamp==e.timestamp)
        before=p.states[p.states.index(state)-1]
        assert before.amounts[e.key]>0
        assert state.amounts[e.key]==0
        assert state.native_cash==before.native_cash


def test_real_valid_states_weights_and_no_negative_areas(integrated):
    wb,r,n,p=integrated
    assert all(s.valid for s in p.states), 'Populate FX cache before running integration tests'
    for s in p.states:
        assert abs(sum(s.weights.values())-100)<=.000001
        assert all(v>=0 for v in s.amounts.values())
        assert s.amounts['Cash']+s.reserved==pytest.approx(max(s.total_cash,0))


def test_distinct_trade_ids_identical_executions_kept(integrated):
    wb,_,_,_=integrated
    copied=deepcopy(wb)
    row=deepcopy(copied['Trades'][0])
    row.update(Trade_ID='ANOTHER_EXECUTION',_source='Trades!999',_row=999)
    copied.sheets['Trades'].append(row)
    normal=Normalizer(copied,Instruments(copied))
    same=[e for e in normal.events if e.timestamp==datetime.fromisoformat(row['Date_Time']) and e.kind=='trade']
    assert len(same)==2
    assert len({e.data['trade_id'] for e in same})==2


def test_exact_repeat_id_suppressed_conflict_rejected(integrated):
    wb,_,_,_=integrated
    copied=deepcopy(wb)
    copied.sheets['Trades'].append(deepcopy(copied['Trades'][0]))
    normal=Normalizer(copied,Instruments(copied))
    assert any(i.code=='duplicate_trade_id' for i in normal.issues)
    copied.sheets['Trades'][-1]['Amount']+=1
    with pytest.raises(ValueError,match='Conflicting duplicate Trade_ID'):
        Normalizer(copied,Instruments(copied))


def test_unknown_spinoff_is_flagged_without_invented_zero(integrated):
    wb,_,_,_=integrated
    registry=Instruments(wb)
    normal=Normalizer(wb,registry,'unknown')
    p=Portfolio(registry.items,FX(ROOT/'fx_cache'))
    p.run(normal.events)
    state=next(s for s in p.states if any(e['kind']=='spinoff' for e in s.events))
    assert state.amounts['US9344231041'] is None
    assert state.amounts['US00206R1023'] is None
    assert not state.valid
    assert any(i.code=='spinoff_basis_unknown' for i in p.issues)


def test_corroborated_spinoff_inference_conserves_group_cost(integrated):
    wb,r,n,p=integrated
    state=next(s for s in p.states if any(e['kind']=='spinoff' for e in s.events))
    before=p.states[p.states.index(state)-1]
    assert state.amounts['US9344231041']==pytest.approx(537.71648796)
    assert state.amounts['US9344231041']+state.amounts['US00206R1023']==pytest.approx(before.amounts['US00206R1023'])
    assert state.basis_status['US9344231041']=='inferred'


def test_reconciliation_exposes_discrepancies_no_adjustment(integrated):
    wb,r,n,p=integrated
    report=reconcile(wb,p,r,n)
    cash=[x for x in report if x['category']=='cash_balance']
    assert len(cash)==9
    assert all(abs(x['difference'])<.000001 for x in cash if x['date'][:4] in ('2021','2022'))
    assert any(abs(x['difference'])>100 for x in cash)
    assert any(x['category'].startswith('source_unprocessed:') for x in report)
    assert all('adjustment' not in x['kind'] for x in p.cash.entries)
    assert p.states[-1].native_cash['USD']==pytest.approx(9994.16387539387)


def test_historical_corporate_identifiers_and_issue_separation(integrated):
    wb,r,n,p=integrated
    first=next(e for e in n.events if e.data.get('trade_id')=='U5157275_2021_2021.csv:5')
    assert first.key=='US46434G7988'
    assert len([e for e in n.events if e.kind=='conversion'])==5
    assert r.items['US91282CLV18'].asset_class=='Government bonds'
    assert r.items['US912797FS14'].asset_class=='Treasury bills'
    assert 'US11135FCT66' in r.items and 'USU1109MAV82' in r.items


def test_real_security_cost_unchanged_between_relevant_transactions(integrated):
    wb,r,n,p=integrated
    for before,after in zip(p.states,p.states[1:]):
        affected=set()
        for event in (e for e in n.events if e.timestamp==after.timestamp):
            if event.kind in ('trade','maturity','full_call','security_in','security_out','conversion','spinoff','option_expiration'):
                affected.add(event.key)
                affected.add(event.data.get('target'))
                affected.add(event.data.get('parent'))
        for key,inst in r.items.items():
            if key not in affected and not inst.is_option:
                assert before.amounts[key]==after.amounts[key]


def test_simultaneous_fx_executions_one_state_both_cash_legs(integrated):
    wb,r,n,p=integrated
    at=datetime(2026,3,17,11,39,34)
    records=[e for e in n.events if e.timestamp==at]
    fx_records=[e for e in records if e.kind=='forex']
    assert len(fx_records)==2 and len({e.data['trade_id'] for e in fx_records})==2
    assert len(records)==3  # Funded EUR security purchase shares this timestamp.
    states=[s for s in p.states if s.timestamp==at]
    assert len(states)==1
    previous=p.states[p.states.index(states[0])-1]
    assert sum(float(e.quantity) for e in fx_records)==pytest.approx(9198.99)
    assert states[0].native_cash['EUR']-previous.native_cash.get('EUR',0)==pytest.approx(-.0072)
    assert states[0].quantities['GB00BJYDH287']==600
    assert len(states[0].events)==3
