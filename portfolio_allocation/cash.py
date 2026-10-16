from collections import defaultdict
from .models import D


class CashLedger:
    def __init__(self):
        self.balances = defaultdict(D)
        self.entries = []

    def post(self,currency,amount,event):
        amount = D(amount)
        self.balances[currency] += amount
        self.entries.append(dict(timestamp=event.timestamp.isoformat(),currency=currency,amount=str(amount),
                                 balance=str(self.balances[currency]),sources=event.sources,kind=event.kind))

    def forex(self,event):
        self.post(event.data['base'],event.quantity,event)
        self.post(event.data['quote'],-event.quantity*event.price,event)
        if event.commission:
            self.post(event.data['commission_currency'],-event.commission,event)

    def security_trade(self,event):
        if event.quantity>0:
            delta = -event.amount-event.commission
        elif event.quantity<0:
            delta = event.amount-event.commission
        else:
            delta = -event.commission
        self.post(event.currency,delta,event)

    def value(self,fx,at):
        total = D()
        used = {}
        for currency,balance in self.balances.items():
            if balance:
                rate,record = fx.rate(currency,at)
                total += balance*rate
                used[currency] = record
        return total,used
