"""Realized profit in original currencies; FX is a display conversion only."""
from collections import Counter,defaultdict
from copy import deepcopy
from .fx import MissingFX
from .models import D,EPS,Issue
from .profit_lots import NativeLots
from .currency_profit import CurrencySettlements
from .profit_audit import ProfitAudit
from .workbook import timestamp

CATEGORIES=('Closed trades','Redemptions','Options','Dividends','Coupons',
            'Interest','Currency borrowing','Currency trades','Corporate actions','Fees / adjustments','Taxes')


class RealizedProfit:
    def __init__(self,fx,fx_records=(),short_premium_policy='closed',display_currency=None):
        self.fx=fx
        self.short_premium_policy=short_premium_policy
        self.requested_currency=display_currency
        self.default_currency='USD'
        self.currencies=['USD']
        self.currency_counts=Counter()
        self.native_totals=defaultdict(lambda:{category:D() for category in CATEGORIES})
        self.totals={category:D() for category in CATEGORIES}
        self.lots=NativeLots()
        self.currency_settlements=CurrencySettlements(fx)
        self.audit=ProfitAudit()
        self.uncertain=set()
        self.short_lots=defaultdict(list)
        self.entries=[]
        self.states=[]
        self.issues=[]
        self.unknown_count=0
        self.inferred_count=0
        self._last_entry=0
        self._valuation_at=None
        self._native_states=[]
        self._missing_rates=set()
        self._audit_fx_ids={row.get('Source_Trade_ID') for row in fx_records if row.get('Operation_Type')=='fx_trade'}

    def issue(self,event,code,details,severity='warning'):
        self.issues.append(Issue(severity,code,details,event.sources,event.key,event.timestamp.isoformat()))

    def post(self,event,category,amount,details,status='documented',currency=None):
        currency=currency or event.currency
        self.currency_counts.setdefault(currency,0)
        if amount is None:
            self.unknown_count+=1
        else:
            amount=D(amount)
            self.native_totals[currency][category]+=amount
        if status=='inferred':
            self.inferred_count+=1
        self.entries.append(dict(timestamp=event.timestamp.isoformat(),instrument_key=event.key,
            category=category,currency=currency,realized_pnl_native=None if amount is None else float(amount),
            status='unknown' if amount is None else status,details=details,sources='; '.join(event.sources),
            unknown_count=self.unknown_count,
            native_cumulative={c:float(sum(v.values(),D())) for c,v in self.native_totals.items()}))

    def close_short(self,key,quantity):
        remaining=D(quantity)
        credit=D()
        for lot in list(self.short_lots[key]):
            if remaining<=EPS:
                break
            take=min(remaining,lot['quantity'])
            part=None if lot['credit'] is None else lot['credit']*take/lot['quantity']
            credit=None if credit is None or part is None else credit+part
            lot['quantity']-=take
            if part is not None:
                lot['credit']-=part
            remaining-=take
            if lot['quantity']<=EPS:
                self.short_lots[key].remove(lot)
        return None if remaining>EPS else credit

    def process(self,e,portfolio):
        self.audit.begin(e,self)
        if e.kind!='checkpoint' and e.currency:
            self.currency_counts[e.currency]+=1
        if e.kind=='income':
            category=e.data.get('sheet','Interest')
            self.post(e,category if category in CATEGORIES else 'Interest',e.amount,e.details)
            if e.commission:
                self.post(e,'Fees / adjustments',-e.commission,'Separate income commission, charged once.')
        elif e.kind=='cash_transfer':
            role=e.data.get('cash_role')
            if role in ('tax','fee_adjustment'):
                self.post(e,'Taxes' if role=='tax' else 'Fees / adjustments',e.amount,e.details)
        elif e.kind=='forex':
            if e.data.get('trade_id') in self._audit_fx_ids and not any(i.code=='fx_audit_pnl_excluded' for i in self.issues):
                self.issue(e,'fx_audit_pnl_excluded','Unverified Fifo FX P/L is excluded. Actual FX closures and currency debt repayments are reconstructed from execution cash flows; ordinary cash is not assigned a hypothetical USD acquisition cost.')
            if e.commission:
                self.post(e,'Fees / adjustments',-e.commission,'Actual FX commission; exchange principal is excluded.',currency=e.data['commission_currency'])
        elif e.kind=='security_in':
            records=e.data.get('basis_lots') or [dict(quantity=e.quantity,cost=e.data.get('basis'),acquired=e.timestamp,status=e.data.get('basis_status','unknown'))]
            for lot in records:
                self.lots.add(e.key,D(lot['quantity']),lot['cost'],e.currency,
                              timestamp(lot['acquired']) if lot.get('acquired') else e.timestamp,lot['status'])
        elif e.kind=='security_out':
            self.lots.remove(e.key,abs(e.quantity))
        elif e.kind=='conversion':
            removed,missing=self.lots.remove(e.key,e.quantity)
            target=e.data['target']
            target_currency=portfolio.instruments[target].currency
            for lot in removed:
                same_currency=lot.currency==target_currency
                self.lots.add(target,lot.quantity*e.data['ratio'],lot.cost if same_currency else None,
                              target_currency,lot.acquired,lot.status if same_currency else 'unknown')
            if e.key in self.uncertain or missing>EPS:
                self.uncertain.add(target)
            if e.amount:
                self.post(e,'Corporate actions',e.amount,e.details)
        elif e.kind=='spinoff':
            parent=e.data.get('parent')
            basis=e.data.get('basis')
            total=self.lots.basis(parent) if parent else None
            valid=e.currency=='USD' and basis is not None and total is not None and D()<basis<total
            if valid:
                for lot in self.lots.lots[parent]:
                    lot.cost-=basis*lot.cost/total
                    lot.status='inferred'
            else:
                basis=None
                if parent:
                    self.uncertain.add(parent)
            self.lots.add(e.key,e.quantity,basis,e.currency,e.timestamp,'inferred' if valid else 'unknown')
        elif e.kind in ('trade','maturity','full_call','redemption','option_expiration','option_assignment','option_exercise'):
            self.security_event(e,portfolio)
        elif e.kind=='unresolved':
            self.post(e,'Corporate actions',None,'Unresolved event can affect native realized profit.')

    def process_cash(self,event,postings):
        self.currency_settlements.process(event,postings,self)
        self.audit.finish(event,postings,self)

    def security_event(self,e,portfolio):
        current=portfolio.fifo.quantity(e.key)
        inst=portfolio.instruments[e.key]
        category='Options' if inst.is_option else ('Redemptions' if e.kind in ('maturity','full_call','redemption') else 'Closed trades')
        expiration=e.kind=='option_expiration'
        if e.kind in ('option_assignment','option_exercise'):
            self.post(e,category,None,'Assignment/exercise needs a verified underlying native-basis linkage.')
            self.issue(e,'exercise_profit_unresolved','Option assignment/exercise needs verified underlying basis.','blocking')
            return
        qty=e.quantity
        size=abs(qty)
        if size<=EPS:
            if e.commission:
                self.post(e,'Fees / adjustments',-e.commission,'Standalone trading commission.')
            return
        if expiration:
            if current*qty>=0 or size>abs(current)+EPS:
                self.post(e,category,None,'Invalid expiration quantity.')
                return
            cash=-e.commission
        else:
            cash=e.amount-e.commission if qty<0 else -e.amount-e.commission
        if qty<0:
            closed=min(size,max(current,D()))
            if closed>EPS:
                removed,missing=self.lots.remove(e.key,closed)
                known=(e.key not in self.uncertain and missing<=EPS and
                       all(lot.cost is not None and lot.currency==e.currency for lot in removed))
                basis=sum((lot.cost for lot in removed),D()) if known else None
                status='unknown' if not known else ('inferred' if any(lot.status=='inferred' for lot in removed) else 'documented')
                self.post(e,category,None if basis is None else cash*closed/size-basis,
                          'Net proceeds minus FIFO acquisition cost in the same original currency.' if not expiration else 'Long option expiration: native premium and fees written off.',status)
            opening=size-closed
            if opening>EPS:
                credit=cash*opening/size
                self.short_lots[e.key].append(dict(quantity=opening,credit=credit,currency=e.currency,is_option=inst.is_option))
                if self.short_premium_policy=='cash' and inst.is_option:
                    self.post(e,category,credit,'Short premium recognized on receipt under explicit cash policy.')
        else:
            closed=min(size,max(-current,D()))
            if closed>EPS:
                credit=self.close_short(e.key,closed)
                if self.short_premium_policy=='cash' and inst.is_option:
                    credit=D()
                self.post(e,category,None if credit is None else credit+cash*closed/size,
                          'Native opening net premium less native closing payment and fees.')
            opening=size-closed
            if opening>EPS:
                self.lots.add(e.key,opening,-cash*opening/size,e.currency,e.timestamp)

    def snapshot(self,at):
        entries=self.entries[self._last_entry:]
        if entries or self._valuation_at is None:
            self._valuation_at=at
        self.states.append(dict(timestamp=at.isoformat(),valuation_timestamp=self._valuation_at.isoformat(),
            is_profit_event=bool(entries),unknown_count=self.unknown_count,inferred_count=self.inferred_count,
            native_cumulative={c:float(sum(values.values(),D())) for c,values in self.native_totals.items()},
            native_by_category={c:{k:float(v) for k,v in values.items()} for c,values in self.native_totals.items()},
            events=entries))
        self._native_states.append(deepcopy(dict(self.native_totals)))
        self._last_entry=len(self.entries)

    def _convert(self,amount,source,target,at,used):
        if amount==0 or source==target:
            return amount
        rates={}
        try:
            for currency in (source,target):
                rates[currency],record=self.fx.rate(currency,at)
                if currency!='USD':
                    used[currency]=record
        except MissingFX as exc:
            signature=(str(exc),at.isoformat())
            if signature not in self._missing_rates:
                self._missing_rates.add(signature)
                self.issues.append(Issue('warning','missing_profit_display_fx',str(exc),[],timestamp=at.isoformat()))
            return None
        return amount*rates[source]/rates[target]

    def _view(self,native,target,at,unknown):
        categories={category:D() for category in CATEGORIES}
        used={}
        for currency,values in native.items():
            for category,amount in values.items():
                converted=self._convert(amount,currency,target,at,used)
                if converted is None or categories[category] is None:
                    categories[category]=None
                else:
                    categories[category]+=converted
        known=None if any(v is None for v in categories.values()) else sum(categories.values(),D())
        complete=unknown==0 and known is not None
        return dict(cumulative_realized=float(known) if complete else None,
                    known_subtotal=None if known is None else float(known),complete=complete,
                    categories={k:None if v is None else float(v) for k,v in categories.items()},fx_used=used)

    def finalize(self):
        self.currencies=sorted(set(self.currency_counts)|{'USD'}|({self.requested_currency} if self.requested_currency else set()))
        self.default_currency=self.requested_currency or min(self.currency_counts or {'USD':0},key=lambda c:(-self.currency_counts[c],c!='USD',c))
        previous={c:0.0 for c in self.currencies}
        for state,native in zip(self.states,self._native_states):
            at=timestamp(state['valuation_timestamp'])
            state['by_currency']={c:self._view(native,c,at,state['unknown_count']) for c in self.currencies}
            for c,view in state['by_currency'].items():
                value=view['cumulative_realized']
                view['display_change']=None if value is None or previous[c] is None else value-previous[c]
                previous[c]=value
            usd=state['by_currency']['USD']
            state.update(cumulative_realized_usd=usd['cumulative_realized'],known_subtotal_usd=usd['known_subtotal'],
                         event_realized_usd=usd['display_change'],cumulative_by_category=usd['categories'],complete=usd['complete'])
        if self.states:
            self.totals={c:None if v is None else D(v) for c,v in self.states[-1]['cumulative_by_category'].items()}
