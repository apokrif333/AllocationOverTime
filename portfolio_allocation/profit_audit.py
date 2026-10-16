"""Audit every event against native cash and deferred security capital.

The invariant is native realized P/L = change in cash plus remaining native
security basis minus deferred short receipts minus capital/exchange principal.
Currency settlement P/L has its separate execution/basis proof, since the native
cash invariant intentionally removes the full exchange principal.
"""
from collections import defaultdict
from .models import D, EPS


def inventory(profit):
    result=defaultdict(D)
    for lots in profit.lots.lots.values():
        for lot in lots:
            if lot.cost is None or result[lot.currency] is None:
                result[lot.currency]=None
            else:
                result[lot.currency]+=lot.cost
    for lots in profit.short_lots.values():
        for lot in lots:
            if profit.short_premium_policy=='cash' and lot.get('is_option'):
                continue
            currency=lot['currency']
            if lot['credit'] is None or result[currency] is None:
                result[currency]=None
            else:
                result[currency]-=lot['credit']
    return dict(result)


class ProfitAudit:
    def __init__(self):
        self.rows=[]

    def begin(self,event,profit):
        self.before=inventory(profit)
        self.entry_start=len(profit.entries)

    def finish(self,event,postings,profit):
        after=inventory(profit)
        cash=defaultdict(D)
        for row in postings:
            cash[row['currency']]+=D(row['amount'])
        posted=defaultdict(D)
        settlements=defaultdict(D)
        for row in profit.entries[self.entry_start:]:
            currency=row['currency']
            target=settlements if row['category'] in ('Currency borrowing','Currency trades') else posted
            if row['realized_pnl_native'] is None or target[currency] is None:
                target[currency]=None
            else:
                target[currency]+=D(row['realized_pnl_native'])
        principal=defaultdict(D)
        reason='income/expense or realized security result; open premiums and purchase fees remain in basis'
        if event.kind=='cash_transfer' and event.data.get('cash_role') not in ('tax','fee_adjustment'):
            principal[event.currency]=event.amount
            reason='external cash capital; not profit'
        elif event.kind in ('security_in','security_out'):
            for currency in set(self.before)|set(after):
                old,new=self.before.get(currency,D()),after.get(currency,D())
                principal[currency]=None if old is None or new is None else new-old
            reason='security capital transfer; no cash or realized profit'
        elif event.kind=='forex':
            principal[event.data['base']]+=event.quantity
            principal[event.data['quote']]-=event.quantity*event.price
            reason='exchange principal excluded; actual closed FX/debt result separately proven in currency_settlements.csv'
        elif event.kind in ('conversion','spinoff'):
            reason='noncash corporate basis continuity; explicit cash proceeds included once'
        elif event.kind=='checkpoint':
            reason='snapshot only; no transaction or profit'
        currencies=set(self.before)|set(after)|set(cash)|set(posted)|set(principal)|set(settlements)
        for currency in sorted(currencies or {event.currency}):
            old,new=self.before.get(currency,D()),after.get(currency,D())
            capital=principal[currency]
            expected=None if old is None or new is None or capital is None else cash[currency]+new-old-capital
            actual=posted[currency]
            difference=None if expected is None or actual is None else actual-expected
            status='unavailable' if difference is None else ('pass' if abs(difference)<=D('.000001') else 'error')
            self.rows.append(dict(timestamp=event.timestamp.isoformat(),kind=event.kind,
                instrument_key=event.key,currency=currency,cash_change=str(cash[currency]),
                deferred_capital_before=None if old is None else str(old),
                deferred_capital_after=None if new is None else str(new),
                excluded_principal=None if capital is None else str(capital),
                expected_native_profit=None if expected is None else str(expected),
                posted_native_profit=None if actual is None else str(actual),
                separately_proven_currency_result=None if settlements[currency] is None else str(settlements[currency]),
                difference=None if difference is None else str(difference),status=status,
                reason=reason,sources='; '.join(event.sources)))


def source_coverage(workbook,normalizer):
    links=defaultdict(list)
    for event in normalizer.events:
        for source in event.sources:
            links[source].append(event)
    result=[]
    for sheet in ('Trades','Transfers','CorporateActions','Dividends','Coupons','Interest'):
        for row in workbook[sheet]:
            events=links[row['_source']]
            duplicate=(sheet=='Trades' and any(i.code=='duplicate_trade_id' and row['_source'] in i.sources for i in normalizer.issues))
            result.append(dict(source=row['_source'],sheet=sheet,currency=row.get('Currency'),
                event_count=len(events),event_kinds='; '.join(e.kind for e in events),
                timestamps='; '.join(e.timestamp.isoformat() for e in events),
                status='linked' if events else ('duplicate_id_suppressed' if duplicate else 'error'),
                explanation='Corporate supplement is evidence, not a second cash transaction.' if sheet=='CorporateActions' and events else ''))
    return result


def fifo_comparison(workbook,normalizer,profit):
    """Independent source P/L check by actual execution ID; no signature dedup."""
    groups=defaultdict(list)
    for row in workbook['Fifo']:
        if row.get('Operation_Type')!='fx_trade' and row.get('Source_Trade_ID'):
            groups[row['Source_Trade_ID']].append(row)
    result=[]
    spin_basis={key:D(e.data['basis']) for e in normalizer.events if e.kind=='spinoff' and e.data.get('basis') is not None
                for key in (e.key,e.data.get('parent')) if key}
    for event in normalizer.events:
        records=groups.get(event.data.get('trade_id'))
        if not records:
            continue
        entries=[e for e in profit.entries if e['category'] in ('Closed trades','Redemptions','Options') and
                 set(e['sources'].split('; '))&set(event.sources)]
        reported=sum((D(r.get('PnL_After_All_Commissions')) for r in records),D())
        actual=None if any(e['realized_pnl_native'] is None for e in entries) else sum((D(e['realized_pnl_native']) for e in entries),D())
        difference=None if actual is None else actual-reported
        spin=event.key in spin_basis and difference is not None and abs(abs(difference)-spin_basis[event.key])<D('.01')
        status='unavailable' if difference is None else ('pass' if abs(difference)<=D('.01') else ('explained_spinoff' if spin else 'error'))
        result.append(dict(timestamp=event.timestamp.isoformat(),instrument_key=event.key,currency=event.currency,
            trade_id=event.data.get('trade_id'),reconstructed=None if actual is None else str(actual),
            reported=str(reported),difference=None if difference is None else str(difference),status=status,
            explanation='Corroborated inferred spinoff allocation; parent/child differences offset.' if spin else '',
            sources='; '.join(event.sources+[r['_source'] for r in records])))
    return result
