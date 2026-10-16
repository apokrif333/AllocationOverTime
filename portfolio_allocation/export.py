import csv
from dataclasses import asdict
from decimal import Decimal
import json


def json_default(value):
    if isinstance(value,Decimal):
        return str(value)
    if hasattr(value,'isoformat'):
        return value.isoformat()
    raise TypeError(type(value).__name__)


TIMESERIES_COLUMNS = ['timestamp','instrument_key','name','isin','asset_class','quantity',
    'invested_usd','weight_percent','basis_status','total_cash_usd','free_cash_usd',
    'reserved_collateral_usd','borrowing_usd','accounting_denominator_usd','net_cost_capital_usd',
    'allocation_valid','native_cash','fx_used','recent_event','event_sources']


def timeseries_rows(states,instruments):
    keys=sorted(instruments)+['Cash']
    for state in states:
        for key in keys:
            inst=instruments.get(key)
            short=inst and inst.is_option and state.quantities.get(key,0)<0
            yield dict(zip(TIMESERIES_COLUMNS,[state.timestamp.isoformat(),key,inst.name if inst else 'Cash',
                inst.isin if inst else '',('Short-option collateral' if short else inst.asset_class) if inst else 'Cash',
                state.quantities.get(key,0),state.amounts.get(key,0),state.weights.get(key,0),state.basis_status.get(key,'documented'),
                state.total_cash,state.free_cash,state.reserved,state.borrowing,state.denominator,state.net_capital,state.valid,
                json.dumps(state.native_cash,sort_keys=True),json.dumps(state.fx_used,sort_keys=True),
                state.last_events.get(key,''),'; '.join(s for e in state.events for s in e['sources'])]))


def write_csv(path,rows,columns=None):
    rows=list(rows)
    fields=columns or list(dict.fromkeys(k for r in rows for k in r))
    with open(path,'w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def write_json(path,data):
    path.write_text(json.dumps(data,default=json_default,ensure_ascii=False,indent=2),encoding='utf-8')


def profit_timeseries_rows(states):
    """One row per timestamp and display currency, with native audit amounts."""
    for state in states:
        for currency,view in state['by_currency'].items():
            yield dict(timestamp=state['timestamp'],valuation_timestamp=state['valuation_timestamp'],
                       display_currency=currency,cumulative_realized=view['cumulative_realized'],
                       known_subtotal=view['known_subtotal'],display_change=view['display_change'],
                       complete=view['complete'],is_profit_event=state['is_profit_event'],
                       unknown_count=state['unknown_count'],inferred_count=state['inferred_count'],
                       native_cumulative=json.dumps(state['native_cumulative'],sort_keys=True),
                       native_by_category=json.dumps(state['native_by_category'],sort_keys=True),
                       fx_used=json.dumps(view['fx_used'],sort_keys=True),**view['categories'])
