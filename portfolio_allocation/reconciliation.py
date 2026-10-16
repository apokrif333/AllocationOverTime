"""Independent comparisons: no balancing entries or cash adjustments."""
from collections import defaultdict
from bisect import bisect_right
from .models import D, Issue
from .workbook import timestamp


def reconcile(wb,portfolio,registry,normalizer):
    rows = []
    states = portfolio.states
    dates = [s.timestamp for s in states]

    def state_on(day):
        from datetime import time
        at = timestamp(day,time(23,59,59))
        index = bisect_right(dates,at)-1
        return states[index] if index>=0 else None

    def compare(kind,day,key,currency,reconstructed,reported,sources,cause,tolerance):
        difference = reconstructed-reported
        relative = abs(difference)/abs(reported) if reported else (0 if not difference else None)
        severity = 'info' if abs(difference)<=tolerance else ('blocking' if kind=='cash_balance' and abs(difference)>100 else 'warning')
        rows.append(dict(category=kind,severity=severity,date=str(day),instrument_key=key,currency=currency,
                         reconstructed=float(reconstructed),reported=float(reported),difference=float(difference),
                         absolute_difference=float(abs(difference)),relative_difference=relative,
                         tolerance=tolerance,sources='; '.join(sources),possible_cause=cause))

    for row in wb['CashBalances']:
        state = state_on(row['Date'])
        actual = state.native_cash.get(row['Currency'],0) if state else 0
        evidence = [e for e in portfolio.cash.entries if e['currency']==row['Currency'] and e['timestamp'][:10]<=str(row['Date'])]
        sources = [row['_source']]+list(dict.fromkeys(s for e in evidence for s in e['sources']))
        compare('cash_balance',row['Date'],'',row['Currency'],actual,float(row['Ending_Cash']),sources,
                'Derived audit may omit fees, cash adjustments, or use an unspecified FX fee currency; trade-date cash convention may differ from settlement. No balancing entry inserted.',.05)
    if (not any(r['Transfer_Type']=='cash' for r in wb['Transfers']) and
            any(r['category']=='cash_balance' and r['reconstructed']<0<=r['reported'] and
                r['absolute_difference']>100 for r in rows)):
        rows.append(dict(category='cash_funding_history_missing',severity='blocking',
            sources='Transfers; CashBalances; cash_ledger.csv',
            possible_cause='No cash funding/withdrawal history is supplied. Recorded security transactions do not reproduce reported positive cash. '
                           'Negative reconstructed cash is an unfunded ledger shortfall, not independently confirmed broker borrowing. '
                           'Original deposits, withdrawals, conversions and/or explicit opening cash are needed; no synthetic funding inserted.'))
    grouped = defaultdict(list)
    for row in wb['Positions']:
        grouped[(str(row['Date']),row.get('ISIN') or row.get('Symbol'),row['Currency'])].append(row)
    # Union includes reconstructed nonzero holdings absent from Positions.
    for day in sorted({k[0] for k in grouped}):
        effective = min(timestamp(day).date(),wb.end_date)
        state = state_on(effective)
        if state is None:
            continue
        present = set()
        for (reported_day,identifier,currency),records in grouped.items():
            if reported_day!=day:
                continue
            key = registry.resolve(records[0])
            present.add(key)
            reported = sum(float(r['Quantity']) for r in records)
            actual = state.quantities.get(key,0)
            cause = 'Positions is a derived lot schedule; historical identifiers may be remapped and transferred-out lots retained.'
            if timestamp(day).date()>wb.end_date:
                cause += f' Forward date label compared against {effective}, not a future broker observation.'
            compare('position_quantity',day,key,currency,actual,reported,[r['_source'] for r in records],cause,1e-7)
        for key,quantity in state.quantities.items():
            if abs(quantity)>1e-7 and key not in present:
                compare('position_quantity',day,key,registry.items[key].currency,quantity,0,
                        [s for e in normalizer.events if e.key==key and e.timestamp<=state.timestamp for s in e.sources],
                        'Reconstructed holding absent from derived snapshot; inspect original identifier and corporate conversion.',1e-7)
    for row in wb['Reconciliation']:
        difference = D(row.get('Difference'))
        report = D(row.get('Broker_Value'))
        # These are original workbook findings, explicitly distinct from our checks.
        tax_only = row['Metric']=='unprocessed_rows' and str(row.get('Details') or '').startswith('missing_kzt_fx_rate:')
        rows.append(dict(category='source_audit:'+str(row['Metric']),severity='warning' if tax_only else row['Severity'],source_severity=row['Severity'],date=str(row.get('Year') or ''),
                         instrument_key=row.get('Instrument_Key') or '',currency=row.get('Currency') or '',
                         reconstructed=row.get('Canonical_Value'),reported=row.get('Broker_Value'),difference=float(difference),
                         absolute_difference=float(abs(difference)),relative_difference=float(abs(difference/report)) if report else None,
                         tolerance=row.get('Tolerance'),sources=row['_source'],possible_cause=row.get('Details') or 'Original workbook audit finding; not this application ledger.'))
    for row in wb['Unprocessed']:
        tax_only = row['Reason']=='missing_kzt_fx_rate'
        rows.append(dict(category='source_unprocessed:'+row['Reason'],severity='warning' if tax_only else row['Severity'],
            date=str(row.get('Date_Time') or ''),instrument_key=row.get('ISIN') or '',currency=row.get('Currency') or '',
            sources=row['_source'],possible_cause=str(row['Details'])+(' Tax KZT fields are not used for USD valuations.' if tax_only else '')))
    for issue in normalizer.issues+portfolio.issues:
        rows.append(dict(category=issue.code,severity=issue.severity,date=issue.timestamp,instrument_key=issue.instrument,
                         sources='; '.join(issue.sources),possible_cause=issue.details))
    # Missing current FX can invalidate a state without a missing acquisition FX.
    missing_states = [s for s in states if not s.valid]
    if missing_states:
        rows.append(dict(category='invalid_allocation_states',severity='blocking',
            date=missing_states[0].timestamp.isoformat(),sources='allocation_timeseries.csv',
            possible_cause=f'{len(missing_states)} states have unknown basis, missing FX or no positive denominator. Weights unavailable, not zero or normalized estimates.'))
    return rows
