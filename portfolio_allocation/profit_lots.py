"""Original-currency FIFO for profit, independent of allocation USD costs."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from .models import D, EPS


@dataclass
class NativeLot:
    quantity: Decimal
    cost: Decimal | None
    currency: str
    acquired: datetime
    status: str


class NativeLots:
    def __init__(self):
        self.lots=defaultdict(list)

    def add(self,key,quantity,cost,currency,acquired,status='documented'):
        if quantity>EPS:
            self.lots[key].append(NativeLot(D(quantity),None if cost is None else D(cost),currency,acquired,status))
            self.lots[key].sort(key=lambda lot:lot.acquired)

    def remove(self,key,quantity):
        remaining=D(quantity)
        removed=[]
        for lot in list(self.lots[key]):
            if remaining<=EPS:
                break
            take=min(remaining,lot.quantity)
            cost=None if lot.cost is None else lot.cost*take/lot.quantity
            removed.append(NativeLot(take,cost,lot.currency,lot.acquired,lot.status))
            lot.quantity-=take
            if cost is not None:
                lot.cost-=cost
            remaining-=take
            if lot.quantity<=EPS:
                self.lots[key].remove(lot)
        return removed,remaining

    def basis(self,key):
        lots=self.lots[key]
        return None if any(lot.cost is None for lot in lots) else sum((lot.cost for lot in lots),D())
