"""Read-only inspection of the supplied audit; writes no workbook data."""
import collections
import json
from pathlib import Path
import openpyxl

path = Path('files/ib_U5157275_audit.xlsx')
wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
data = {}
for ws in wb:
    rows = list(ws.values)
    data[ws.title] = [dict(zip(rows[0], row), _row=i) for i, row in enumerate(rows[1:], 2)]

def show(sheet, predicate=lambda r: True, fields=None):
    print('\n' + sheet)
    for r in data[sheet]:
        if predicate(r):
            print(json.dumps({k:v for k,v in r.items() if fields is None or k in fields}, default=str))

for s in ['Trades', 'Transfers', 'CorporateActions', 'Instruments', 'Reconciliation']:
    for f in {'Trades':['Trade_Type','Asset_Type','Currency'], 'Transfers':['Transfer_Type','Direction'], 'CorporateActions':['Action_Type'], 'Instruments':['Type'], 'Reconciliation':['Metric','Severity']}[s]:
        print(s, f, collections.Counter(str(r[f]) for r in data[s]))
show('Transfers')
show('CorporateActions')
show('Trades', lambda r: r['Asset_Type'] != 'Stocks', ['_row','Date_Time','Trade_ID','Trade_Type','Symbol','ISIN','Asset_Type','Quantity','Price','Multiplier','Amount','Commission','Amount_With_Commission','Currency'])
show('Fifo', lambda r:r['ISIN']=='US912797FS14')
show('Instruments', lambda r:r['Type'] not in ('COMMON','ETF'), ['Symbol','Description','Type','Multiplier','Expiry','Strike','Underlying','ISIN','Security_ID'])
show('CashBalances')
show('Reconciliation', lambda r:r['Severity']=='error')
show('Positions', lambda r:str(r['Date'])>='2026')
