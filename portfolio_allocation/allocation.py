"""Replay events into holdings, native cash, and full-portfolio allocation states."""
from dataclasses import asdict
from itertools import groupby
from .cash import CashLedger
from .derivatives import collateral
from .fifo import FIFO
from .fx import MissingFX
from .models import D, EPS, Issue, State


class Portfolio:
    def __init__(self,instruments,fx,collateral_policy='cash-secured-puts',profit=None):
        self.instruments,self.fx = instruments,fx
        self.fifo,self.cash = FIFO(),CashLedger()
        self.issues = []
        self.states = []
        self.policy = collateral_policy
        self.profit = profit
        self.recent = {}
        self.uncertain = set()
        self.basis_failure = set()
        self.event_audit = []
        self.unresolved_events = []

    def issue(self,severity,code,details,event):
        self.issues.append(Issue(severity,code,details,event.sources,event.key,event.timestamp.isoformat()))
        if severity=='blocking' and code not in ('missing_acquisition_fx','spinoff_basis_unknown','transfer_basis_unknown'):
            self.unresolved_events.append(f'{code}: {details}')

    def _cost(self,amount,currency,event):
        try:
            return self.fx.usd(amount,currency,event.timestamp)
        except MissingFX as exc:
            self.issue('blocking','missing_acquisition_fx',str(exc),event)
            self.basis_failure.add(event.key)
            return None

    def apply(self,e):
        self.recent[e.key or 'Cash'] = e.details
        audit = asdict(e)
        if e.kind in ('cash_transfer','income'):
            self.cash.post(e.currency,e.amount,e)
            if e.kind=='income' and e.commission:
                self.cash.post(e.currency,-e.commission,e)
        elif e.kind=='forex':
            self.cash.forex(e)
        elif e.kind=='security_in':
            basis = e.data.get('basis')
            status = e.data.get('basis_status','unknown')
            if e.data.get('basis_lots'):
                from dataclasses import replace
                from .workbook import timestamp
                usd = D()
                for record in e.data['basis_lots']:
                    acquired = timestamp(record['acquired']) if record['acquired'] else e.timestamp
                    cost = self._cost(record['cost'],e.currency,replace(e,timestamp=acquired))
                    self.fifo.add(e.key,record['quantity'],cost,acquired,record['source'],record['status'])
                    usd = None if usd is None or cost is None else usd+cost
            else:
                usd = self._cost(basis,e.currency,e) if basis is not None else None
                self.fifo.add(e.key,e.quantity,usd,e.timestamp,';'.join(e.sources),status)
            if status!='documented':
                self.issue('warning' if usd is not None else 'blocking','transfer_basis_'+status,
                    f'Incoming security basis is {status}: {basis} {e.currency}; no cash purchase. Evidence: {e.data.get("basis_sources")}',e)
        elif e.kind=='security_out':
            removed,missing = self.fifo.remove(e.key,abs(e.quantity))
            if missing>EPS:
                self.issue('blocking','transfer_quantity_exceeds_holdings',f'Cannot remove {missing} units without acquisition lots.',e)
            audit['removed_basis_usd'] = None if any(l.cost_usd is None for l in removed) else str(sum((l.cost_usd for l in removed),D()))
        elif e.kind=='conversion':
            target = e.data['target']
            remaining = self.fifo.convert(e.key,target,e.quantity,e.data['ratio'])
            if remaining>EPS:
                self.issue('blocking','corporate_quantity_exceeds_holdings',f'Conversion missing {remaining} source units.',e)
            if e.key in self.uncertain:
                self.uncertain.add(target)
            if e.amount:
                self.cash.post(e.currency,e.amount,e)
            self.recent[target] = e.details
        elif e.kind=='spinoff':
            parent = e.data.get('parent')
            basis = e.data.get('basis')
            if basis is not None and parent and self.fifo.basis(parent) is not None and D(0)<basis<self.fifo.basis(parent):
                # Separate the child allocation proportionally from existing
                # parent lots, conserving the combined USD cost exactly.
                total = self.fifo.basis(parent)
                for lot in self.fifo.lots[parent]:
                    if lot.quantity>0:
                        lot.cost_usd *= (total-basis)/total
                        lot.basis_status = 'inferred'
                self.fifo.add(e.key,e.quantity,basis,e.timestamp,';'.join(e.sources),'inferred')
                self.issue('warning','spinoff_basis_inferred',
                    f'USD {basis} allocated from parent using later broker P/L with equal/opposite parent discrepancy. Retrospective inference, not independently verified purchase basis. {e.data.get("basis_sources")}',e)
            else:
                self.fifo.add(e.key,e.quantity,None,e.timestamp,';'.join(e.sources),'unknown')
                if parent:
                    self.uncertain.add(parent)
                self.issue('blocking','spinoff_basis_unknown','Child allocation missing; parent/child basis unresolved. No zero basis invented. Optional --spinoff-policy broker-pl requires corroborating source records.',e)
        elif e.kind in ('trade','maturity','full_call','redemption','option_expiration','option_assignment','option_exercise'):
            inst = self.instruments[e.key]
            if e.kind=='option_expiration' or (e.kind in ('option_assignment','option_exercise') and not e.amount):
                current = self.fifo.quantity(e.key)
                if current*e.quantity>=0 or abs(e.quantity)>abs(current)+EPS:
                    self.issue('blocking','invalid_option_close','Expiration/exercise quantity does not close existing contracts.',e)
                else:
                    self.fifo.trade(e.key,e.quantity,D(),e.timestamp,';'.join(e.sources))
                if e.kind!='option_expiration':
                    self.issue('warning','exercise_underlying_check','Option closed without synthetic cash; separately recorded underlying delivery/payment must be reconciled.',e)
                if e.commission:
                    self.cash.post(e.currency,-e.commission,e)
            else:
                cost = self._cost(e.amount+e.commission,e.currency,e) if e.quantity>0 else D()
                removed = self.fifo.trade(e.key,e.quantity,cost,e.timestamp,';'.join(e.sources))
                self.cash.security_trade(e)
                audit['removed_basis_usd'] = None if any(l.cost_usd is None for l in removed) else str(sum((l.cost_usd for l in removed),D()))
                if self.fifo.quantity(e.key)<-EPS and not inst.is_option:
                    self.issue('blocking','uncovered_security_short','Sale/redemption exceeds known long lots. Signed exposure retained, no positive acquisition capital invented.',e)
        elif e.kind=='unresolved':
            self.issue('blocking','unprocessed_event','Unrecognized event retained in audit, not guessed.',e)
        elif e.kind!='checkpoint':
            raise ValueError(f'Unknown event kind {e.kind}')
        self.event_audit.append(audit)

    def snapshot(self,at,events):
        warnings = list(self.unresolved_events)
        try:
            total_cash,used = self.cash.value(self.fx,at)
        except MissingFX as exc:
            total_cash,used = None,{}
            warnings.append(str(exc))
        amounts,quantities,statuses = {},{},{}
        for key in sorted(self.instruments):
            quantity = self.fifo.quantity(key)
            basis = self.fifo.basis(key)
            if quantity>EPS and key in self.uncertain:
                basis = None
            amounts[key] = None if basis is None else float(basis)
            quantities[key] = float(quantity)
            statuses[key] = self.fifo.basis_status(key)
            if basis is None:
                statuses[key] = 'unknown'
                warnings.append(f'Unresolved historical basis: {self.instruments[key].name}')
        reserves,requirements,derivative_warnings = collateral(self.fifo,self.instruments,self.fx,at,total_cash or D(),self.policy)
        warnings.extend(derivative_warnings)
        reserved = sum(reserves.values(),D())
        for key,value in reserves.items():
            amounts[key] = float(value)
            statuses[key] = 'estimated cash-secured collateral; not broker margin'
        free = None if total_cash is None else total_cash-reserved
        cash_component = None if free is None else max(free,D())
        amounts['Cash'] = None if cash_component is None else float(cash_component)
        statuses['Cash'] = 'native cash less reserved collateral'
        unresolved = any(v is None for v in amounts.values())
        denominator = None if unresolved else sum(amounts.values())
        valid = denominator is not None and denominator>0 and not self.unresolved_events
        weights = {k:(100*v/denominator if valid else None) for k,v in amounts.items()}
        borrowing = None if total_cash is None else max(-total_cash,D())
        if borrowing:
            warnings.append('Borrowing: chart shows positive gross capital, not net account equity')
        if valid and abs(sum(weights.values())-100)>0.000001:
            raise ArithmeticError(f'Allocation weights do not sum to 100% at {at}')
        net = None if denominator is None else denominator-float(borrowing or 0)
        event_info = [dict(kind=e.kind,key=e.key,sources=e.sources,details=e.details) for e in events]
        state = State(at,amounts,weights,quantities,{k:float(v) for k,v in self.cash.balances.items()},
            None if total_cash is None else float(total_cash),None if free is None else float(free),float(reserved),
            None if borrowing is None else float(borrowing),denominator,net,valid,statuses,used,event_info,warnings,dict(self.recent))
        self.states.append(state)
        return state

    def run(self,events):
        for at,group in groupby(events,key=lambda e:e.timestamp):
            batch = list(group)
            for event in batch:
                if self.profit is not None:
                    self.profit.process(event,self)
                    cash_start=len(self.cash.entries)
                self.apply(event)
                if self.profit is not None:
                    self.profit.process_cash(event,self.cash.entries[cash_start:])
            self.snapshot(at,batch)
            if self.profit is not None:
                self.profit.snapshot(at)
        if self.profit is not None:
            self.profit.finalize()
        return self.states
