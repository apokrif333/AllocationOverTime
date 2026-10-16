"""Interpret paired corporate records; never use accounting Value as cash."""
from collections import defaultdict
from datetime import time
import re
from .models import D, Event, Issue
from .workbook import timestamp

ISIN_PATTERN = r'[A-Z]{2}[A-Z0-9]{9}\d'


def target_isin(row):
    # The final parenthesized payload describes the delivered/removed instrument.
    tail = str(row.get('Description') or '').rsplit('(',1)[-1]
    matches = re.findall(ISIN_PATTERN,tail)
    return matches[-1] if matches else row.get('ISIN')


class CorporateActions:
    def __init__(self, wb, registry):
        self.edges = []
        self.events = []
        self.issues = []
        groups = defaultdict(list)
        for row in wb['CorporateActions']:
            if row['Action_Type'] in ('merger','merged','tender'):
                groups[(row['Date'],row.get('ISIN'),row['Action_Type'])].append(row)
        for (day,old,action),rows in sorted(groups.items()):
            negative = [r for r in rows if D(r['Quantity']) < 0]
            positive = [r for r in rows if D(r['Quantity']) > 0]
            if len(negative) != 1 or len(positive) != 1:
                self.issues.append(Issue('blocking','unpaired_corporate_action',
                    f'Cannot reliably convert {action} quantities.',[r['_source'] for r in rows],old or '',str(day)))
                self.events.append(Event(timestamp(day,time(20,25)),'unresolved',old or '',sources=[r['_source'] for r in rows],details=f'Unpaired {action} records'))
                continue
            neg,pos = negative[0],positive[0]
            new = target_isin(pos)
            if not old or not new or old == new:
                self.issues.append(Issue('blocking','ambiguous_corporate_identifier',
                    'No distinct delivered instrument identifier.',[r['_source'] for r in rows],old or '',str(day)))
                self.events.append(Event(timestamp(day,time(20,25)),'unresolved',old or '',sources=[r['_source'] for r in rows],details='Ambiguous conversion identifiers'))
                continue
            at = timestamp(day,time(20,25))
            ratio = D(pos['Quantity']) / abs(D(neg['Quantity']))
            self.edges.append((at,old,new,ratio))
            for key in (old,new):
                registry.resolve(dict(ISIN=key,Asset_Type='Stocks' if action=='merger' else 'Bonds',Currency=pos['Currency']))
            self.events.append(Event(at,'conversion',old,pos['Currency'],abs(D(neg['Quantity'])),
                sum((D(r['Proceeds']) for r in rows),D()),sources=[r['_source'] for r in rows],
                details=f'{action}: {old} -> {new}; quantity ratio {ratio}; carry historical lots',
                priority=40,row=neg['_row'],data={'target':new,'ratio':ratio}))

    def historical_isin(self, isin, at):
        # Audit canonicalization mapped earlier trades to final successor IDs.
        # Reverse only explicit corporate conversion chains before their dates.
        seen = set()
        while isin not in seen:
            seen.add(isin)
            applicable = [(dt,old) for dt,old,new,ratio in self.edges if new==isin and at<dt and ratio==1]
            if not applicable:
                break
            isin = max(applicable)[1]
        return isin
