"""Real currency settlements only; ordinary native cash has no invented USD cost.

A negative native cash balance records borrowed units. An actual exchange that
repays those units closes the corresponding debt. Positive cash gets a currency
trading cost only when it was actually purchased in an FX transaction. Income,
deposits, security proceeds, spending and snapshots never realize cash FX P/L.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from .models import D, EPS
from .fx import MissingFX


@dataclass
class CurrencyLot:
    quantity: Decimal
    cost: Decimal | None
    cost_currency: str
    acquired: datetime
    sources: list
    debt: bool = False


class CurrencySettlements:
    def __init__(self, fx):
        self.fx = fx
        self.lots = defaultdict(list)
        self.audit = []

    def process(self, event, postings, profit):
        for index, posting in enumerate(postings):
            currency = posting['currency']
            if currency == 'USD':
                continue
            delta = D(posting['amount'])
            if abs(delta) <= EPS:
                continue
            exchange = event.kind == 'forex' and index < 2
            other = None
            settlement = None
            if exchange:
                base, quote = event.data['base'], event.data['quote']
                other = quote if currency == base else base
                settlement = abs(event.quantity * event.price) if currency == base else abs(event.quantity)
            remaining = abs(delta)
            for lot in list(self.lots[currency]):
                if remaining <= EPS:
                    break
                if (delta > 0) != lot.debt:
                    continue
                take = min(remaining, lot.quantity)
                basis = None if lot.cost is None else lot.cost * take / lot.quantity
                paid = None if settlement is None else settlement * take / abs(delta)
                # Unpriced debt uses the documented daily rate at borrowing.
                # This valuation is never applied to positive ordinary cash.
                if exchange and lot.debt and basis is None:
                    try:
                        basis = self.fx.usd(take, currency, lot.acquired)
                    except MissingFX:
                        pass
                if exchange and (lot.debt or lot.cost is not None):
                    category = 'Currency borrowing' if lot.debt else 'Currency trades'
                    comparable = lot.cost_currency == other
                    result = None if basis is None or not comparable else (basis-paid if lot.debt else paid-basis)
                    details = (f'{currency} {"debt repayment" if lot.debt else "FX position closed"}: '
                               f'{take} units; historical {lot.cost_currency} basis {basis}; '
                               f'actual {other} settlement {paid}.')
                    profit.post(event, category, result, details,
                                'rate-derived' if lot.debt and lot.cost is None else 'documented', currency=other)
                    record = dict(timestamp=event.timestamp.isoformat(), category=category,
                        native_currency=currency, quantity=str(take), profit_currency=other,
                        historical_basis=None if basis is None else str(basis),
                        settlement_amount=str(paid), realized_profit=None if result is None else str(result),
                        basis_method='daily rate at borrowing' if lot.debt and lot.cost is None else 'actual FX execution',
                        acquisition_date=lot.acquired.isoformat(),
                        acquisition_sources='; '.join(lot.sources), settlement_sources='; '.join(event.sources))
                    self.audit.append(record)
                    if result is None:
                        profit.issue(event, 'currency_settlement_basis_unknown',
                            'Actual currency settlement lacks a comparable historical basis. '
                            'No zero cost or 1:1 FX substitution is used.', 'blocking')
                original = lot.quantity
                lot.quantity -= take
                if lot.cost is not None:
                    lot.cost -= lot.cost * take / original
                remaining -= take
                if lot.quantity <= EPS:
                    self.lots[currency].remove(lot)
            if remaining > EPS:
                cost = None if settlement is None else settlement * remaining / abs(delta)
                self.lots[currency].append(CurrencyLot(remaining, cost, other or 'USD',
                                                       event.timestamp, list(event.sources), delta < 0))
