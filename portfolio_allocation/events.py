"""Normalize independent movements and attach duplicate corporate evidence."""
from datetime import time
from .corporate_actions import CorporateActions
from .models import D, Event, Issue
from .workbook import timestamp


class Normalizer:
    def __init__(self, wb, registry, spinoff_policy='unknown', fx_commission_currency='USD'):
        self.wb,self.registry = wb,registry
        self.ca = CorporateActions(wb,registry)
        self.issues = list(wb.issues)+self.ca.issues
        self.events = list(self.ca.events)
        self.spinoff_policy = spinoff_policy
        self.fx_commission_currency = fx_commission_currency
        self.normalize()

    def historical_key(self,row,at):
        original = row.get('ISIN')
        effective = self.ca.historical_isin(original,at) if original else None
        key = self.registry.resolve(row,override_isin=effective)
        if effective != original:
            self.issues.append(Issue('warning','historical_identifier_restored',
                f'Audit ISIN {original} resolved to {effective} before explicit corporate conversion.',
                [row['_source']],key,at.isoformat()))
        return key

    def _spinoff_data(self,row):
        at = timestamp(row['Date_Time'])
        records = [r for r in self.wb['CorporateActions'] if r['Action_Type']=='spinoff' and timestamp(r['Date']).date()==at.date()]
        if len(records)!=1:
            return {}
        parent = records[0].get('ISIN')
        info = {'parent':parent,'basis':None,'basis_sources':[records[0]['_source']]}
        if self.spinoff_policy != 'broker-pl':
            return info
        # Optional auditable inference: child's COMPLETE later disposal and broker
        # P/L imply a cost, corroborated by the equal/opposite parent P/L error.
        child = row['ISIN']
        exits = [r for r in self.wb['Trades'] if r.get('ISIN')==child and D(r['Quantity'])<0 and r['Trade_Type']=='trade']
        if sum((-D(r['Quantity']) for r in exits),D()) != D(row['Quantity']):
            return info
        if not exits or len({timestamp(r['Date_Time']).year for r in exits})!=1:
            return info
        year = timestamp(exits[0]['Date_Time']).year
        child_pl = [r for r in self.wb['Reconciliation'] if r['Metric']=='pnl_after_all_commissions_by_instrument' and r['Instrument_Key']==child and r['Year']==year]
        parent_pl = [r for r in self.wb['Reconciliation'] if r['Metric']=='pnl_after_all_commissions_by_instrument' and r['Instrument_Key']==parent and abs(D(r.get('Difference'))) > 0]
        if len(child_pl)!=1 or len(parent_pl)!=1:
            return info
        basis = sum((D(r['Amount'])-D(r['Commission']) for r in exits),D())-D(child_pl[0]['Broker_Value'])
        offset = D(parent_pl[0]['Broker_Value'])-D(parent_pl[0]['Canonical_Value'])
        if basis>0 and abs(basis-offset)<D('.01'):
            info.update(basis=basis,basis_sources=[r['_source'] for r in exits+child_pl+parent_pl+records])
        return info

    def normalize(self):
        seen_ids = {}
        trade_events = []
        for row in self.wb['Trades']:
            trade_id = row.get('Trade_ID')
            signature = {k:v for k,v in row.items() if not k.startswith('_') and k!='Source_Report'}
            if trade_id and trade_id in seen_ids:
                if seen_ids[trade_id] != signature:
                    raise ValueError(f'Conflicting duplicate Trade_ID {trade_id}')
                self.issues.append(Issue('warning','duplicate_trade_id','Exact duplicate Trade_ID suppressed.',[row['_source']]))
                continue
            if trade_id:
                seen_ids[trade_id] = signature
            at = timestamp(row['Date_Time'])
            typ = row['Trade_Type'] or 'trade'
            kind = 'forex' if row.get('Asset_Type')=='Forex' else 'trade'
            if typ.startswith('corporate_action:'):
                kind = typ.split(':',1)[1]
            elif typ in ('option_expiration','option_assignment','option_exercise'):
                kind = typ
            elif typ=='redemption':
                kind = 'redemption'
            if kind not in ('trade','forex','maturity','full_call','redemption','spinoff','option_expiration','option_assignment','option_exercise'):
                self.issues.append(Issue('blocking','unsupported_trade_semantics',f'Unrecognized Trade_Type {typ}',[row['_source']],timestamp=at.isoformat()))
                kind = 'unresolved'
            key = '' if kind=='forex' else self.historical_key(row,at)
            data = {'trade_id':trade_id,'trade_type':typ,'original_isin':row.get('ISIN')}
            if kind=='forex':
                pair = str(row['Symbol']).split('.')
                if len(pair)!=2:
                    raise ValueError(f'Unknown Forex pair at {row["_source"]}')
                data.update(base=pair[0],quote=pair[1],commission_currency=(pair[1] if self.fx_commission_currency=='quote' else 'USD'))
                if D(row['Commission']):
                    self.issues.append(Issue('warning','fx_commission_currency_assumed',
                        f'No fee currency in audit; using {data["commission_currency"]}. Configure --fx-commission-currency.',[row['_source']],timestamp=at.isoformat()))
            if kind=='spinoff':
                data.update(self._spinoff_data(row))
            amount,fee = D(row['Amount']),D(row['Commission'])
            if row.get('Amount_With_Commission') is not None and abs(D(row['Amount_With_Commission'])-amount-fee)>D('.00001'):
                self.issues.append(Issue('warning','amount_with_commission_mismatch',
                    'Using Amount and Commission once, not Amount_With_Commission.',[row['_source']],key,at.isoformat()))
            e = Event(at,kind,key,row['Currency'],D(row['Quantity']),amount,fee,D(row['Price']),
                      [row['_source']],f'{typ}: {row.get("Symbol")} quantity {row["Quantity"]}; ID {trade_id}',50,row['_row'],data)
            self.events.append(e)
            trade_events.append(e)
        used_transfer_basis = set()
        for row in self.wb['Transfers']:
            at = timestamp(row['Date'])
            incoming = row['Direction']=='in'
            sign = D(1) if incoming else D(-1)
            transfer_type = row['Transfer_Type']
            if row['Direction'] not in ('in','out') or transfer_type not in ('cash','security','tax'):
                raise ValueError(f'Unknown transfer direction/type: {row["_source"]} '
                                 f'(type={transfer_type!r}, direction={row["Direction"]!r})')
            kind = 'cash_transfer' if transfer_type in ('cash','tax') else ('security_in' if incoming else 'security_out')
            key = '' if kind=='cash_transfer' else self.historical_key(row,at)
            data = {'basis':None,'basis_status':'unknown'}
            if transfer_type=='tax':
                # A separately reported withholding/refund is an actual cash
                # expense/income, never an external capital withdrawal/deposit.
                data['cash_role']='tax'
            if transfer_type=='cash' and any(term in str(row.get('Broker_Comment') or '').lower() for term in ('commission adjustment','fee refund','commission refund')):
                data['cash_role']='fee_adjustment'
            if kind=='security_in':
                # Never use a sale's value as entry cost. Prefer explicitly linked
                # FIFO acquisition records; split rows are summed, not deduped.
                raw_acquisitions = {timestamp(r['Date_Time']) for r in self.wb['Trades']
                                    if r.get('ISIN')==row.get('ISIN') and D(r['Quantity'])>0}
                candidates = [r for r in self.wb['Fifo'] if r.get('ISIN')==row.get('ISIN') and
                              r['_source'] not in used_transfer_basis and
                              (not r.get('Enter_Date') or timestamp(r['Enter_Date'])<=at) and
                              (not r.get('Enter_Date') or timestamp(r['Enter_Date']) not in raw_acquisitions)]
                # One ISIN can arrive in separate lots on the same transfer day.
                # Match the original acquisition timestamp supplied by Transfers,
                # rather than comparing each transfer with all of that ISIN's lots.
                if row.get('Enter_Date'):
                    acquired = timestamp(row['Enter_Date'])
                    candidates = [r for r in candidates if r.get('Enter_Date') and
                                  (timestamp(r['Enter_Date']).date()==acquired.date()
                                   if len(str(row['Enter_Date']))==10 else timestamp(r['Enter_Date'])==acquired)]
                qty = sum((D(r['Enter_Quantity']) for r in candidates),D())
                # Some broker audits fill missing transferred acquisition cost
                # with zero. Without an acquisition date that is not evidence
                # of a free acquisition, and would inflate later realized P/L.
                missing_cost = [r for r in candidates if not r.get('Enter_Date') and D(r.get('Enter_Amount'))==0]
                if missing_cost:
                    data['basis_sources']=[r['_source'] for r in candidates]
                    self.issues.append(Issue('blocking','transfer_zero_cost_placeholder',
                        'FIFO transfer entries have zero cost and no acquisition date; original basis is unknown, not zero.',
                        [row['_source']]+[r['_source'] for r in missing_cost],key,at.isoformat()))
                elif candidates and abs(qty-abs(D(row['Quantity'])))<D('.00000001') and all(r.get('Enter_Amount') is not None for r in candidates):
                    data.update(basis=sum((D(r['Enter_Amount'])+D(r.get('Enter_Commission')) for r in candidates),D()),
                                basis_status='inferred' if any(not r.get('Enter_Date') for r in candidates) else 'documented',
                                basis_sources=[r['_source'] for r in candidates],
                                basis_lots=[dict(quantity=D(r['Enter_Quantity']),
                                    cost=D(r['Enter_Amount'])+D(r.get('Enter_Commission')),
                                    acquired=r.get('Enter_Date'),source=r['_source'],
                                    status='inferred' if not r.get('Enter_Date') else 'documented') for r in candidates])
                    used_transfer_basis.update(r['_source'] for r in candidates)
                elif row.get('Amount') is not None and abs(D(row['Amount']))>0:
                    data.update(basis=abs(D(row['Amount'])),basis_status='inferred',basis_sources=[row['_source']])
                # A transfer's quoted Price alone does not establish original
                # acquisition cost (and bonds may be quoted per 100 face).
            self.events.append(Event(at,kind,key,row['Currency'],abs(D(row['Quantity']))*sign,
                abs(D(row['Amount']))*sign,sources=[row['_source']],
                details=f'{transfer_type}: {row.get("Symbol") or row.get("Broker_Comment")}; '
                        + ('no cash for security transfers' if transfer_type=='security' else f'{abs(D(row["Amount"]))*sign} {row["Currency"]}'),
                priority=10 if kind=='cash_transfer' else 20,row=row['_row'],data=data))
        for sheet in ('Dividends','Coupons','Interest'):
            for row in self.wb[sheet]:
                at = timestamp(row.get('Pay_Date') or row['Date'],time(23,59))
                key = self.historical_key(row,at) if row.get('ISIN') or row.get('Symbol') else ''
                net = row.get('Net_Amount')
                if net is None:
                    gross,tax = row.get('Gross_Amount'),row.get('Withholding_Tax')
                    if gross is None or tax is None:
                        raise ValueError(f'Missing net income at {row["_source"]}')
                    net = D(gross)+D(tax)
                # Net_Amount includes withholding. A separately populated fee
                # is charged only when the supplied gross/net identity proves
                # that it is not already included (e.g. Tsifra repo interest).
                fee = abs(D(row.get('Commission')))
                if fee:
                    before_fee = D(row.get('Gross_Amount'))+D(row.get('Withholding_Tax'))
                    if row.get('Gross_Amount') is not None and abs(D(net)-(before_fee-fee))<D('.00000001'):
                        fee = D()
                    elif row.get('Gross_Amount') is None or abs(D(net)-before_fee)>D('.00000001'):
                        self.issues.append(Issue('blocking','income_fee_ambiguous',
                            'Cannot determine whether Net_Amount already includes Commission.',[row['_source']],key,at.isoformat()))
                        self.events.append(Event(at,'unresolved',key,sources=[row['_source']],details='Ambiguous income commission'))
                        fee = D()
                self.events.append(Event(at,'income',key,row['Currency'],amount=D(net),commission=fee,
                    sources=[row['_source']],details=f'{sheet}: {row.get("Description") or row.get("Symbol")}; net {net} {row["Currency"]}',
                    priority=70,row=row['_row'],data={'sheet':sheet}))
        consumed = set()
        for row in self.wb['CorporateActions']:
            typ = row['Action_Type']
            if typ in ('merger','merged','tender'):
                continue
            day = timestamp(row['Date']).date()
            if typ=='spinoff':
                matches = [e for e in trade_events if e.kind=='spinoff' and e.timestamp.date()==day]
            else:
                equivalents = (typ,'redemption') if typ in ('maturity','full_call') else (typ,)
                matches = [e for e in trade_events if e.kind in equivalents and e.timestamp.date()==day
                           and e.key==row.get('ISIN') and e.currency==row['Currency']
                           and abs(e.quantity-D(row['Quantity']))<D('.00000001')
                           and abs(e.amount-D(row['Proceeds']))<D('.01') and id(e) not in consumed]
            if len(matches)==1:
                if matches[0].kind=='redemption':
                    # Halyk uses redemption in Trades and maturity in the
                    # supplementary sheet. Preserve trade proceeds/fees once.
                    matches[0].kind=typ
                matches[0].sources.append(row['_source'])
                consumed.add(id(matches[0]))
            elif typ in ('maturity','full_call'):
                # If matching metadata differ, do not create a second possible
                # redemption. Block and expose it for manual resolution.
                similar = [e for e in trade_events if e.key==row.get('ISIN') and e.timestamp.date()==day and e.kind in ('maturity','full_call','redemption')]
                if similar:
                    self.issues.append(Issue('blocking','ambiguous_redemption_duplicate','Corporate proceeds/quantity disagree with trade.',[row['_source']]+[s for e in similar for s in e.sources],row.get('ISIN') or '',str(day)))
                    self.events.append(Event(timestamp(row['Date'],time(20,25)),'unresolved',row.get('ISIN') or '',sources=[row['_source']],details='Ambiguous redemption duplicate'))
                else:
                    at = timestamp(row['Date'],time(20,25))
                    key = self.historical_key(row,at)
                    self.events.append(Event(at,typ,key,row['Currency'],D(row['Quantity']),D(row['Proceeds']),
                        sources=[row['_source']],details=str(row['Description']),priority=40,row=row['_row']))
            else:
                self.issues.append(Issue('blocking','unresolved_corporate_action',str(row['Description']),[row['_source']],row.get('ISIN') or '',str(day)))
                self.events.append(Event(timestamp(row['Date'],time(20,25)),'unresolved',row.get('ISIN') or '',sources=[row['_source']],details='Unresolved corporate action'))
        # Snapshot checkpoints update FX and permit exact-date comparisons, with
        # no invented cash movements. Future derived labels are capped explicitly.
        dates = {min(timestamp(r['Date']).date(),self.wb.end_date) for s in ('Positions','CashBalances') for r in self.wb[s]}
        dates.add(self.wb.end_date)
        for day in sorted(dates):
            self.events.append(Event(timestamp(day,time(23,59,59)),'checkpoint',details='Account snapshot checkpoint; no transaction',priority=99))
        self.events.sort(key=lambda e:(e.timestamp,e.priority,e.row,e.kind,e.key))
