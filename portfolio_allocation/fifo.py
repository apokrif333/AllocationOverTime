"""Decimal FIFO quantities and USD acquisition basis, including short positions."""
from collections import defaultdict
from .models import D, EPS, Lot


class FIFO:
    def __init__(self):
        self.lots = defaultdict(list)

    def quantity(self,key):
        return sum((l.quantity for l in self.lots[key]),D())

    def basis(self,key):
        longs = [l for l in self.lots[key] if l.quantity>0]
        if any(l.cost_usd is None for l in longs):
            return None
        return sum((l.cost_usd for l in longs),D())

    def basis_status(self,key):
        statuses = {l.basis_status for l in self.lots[key] if l.quantity>0}
        return 'unknown' if 'unknown' in statuses else ('inferred' if 'inferred' in statuses else 'documented')

    def add(self,key,quantity,cost,at,source,status='documented'):
        if quantity:
            self.lots[key].append(Lot(D(quantity),D(cost) if cost is not None else None,at,source,status))
            # Transferred lots can arrive together in a different source-row
            # order from their original purchases. FIFO follows acquisition time.
            self.lots[key].sort(key=lambda lot:lot.opened)

    def remove(self,key,quantity):
        """Remove positive quantity in FIFO order; return removed lots, remainder."""
        remaining = D(quantity)
        removed = []
        for lot in list(self.lots[key]):
            if lot.quantity<=0 or remaining<=EPS:
                continue
            take = min(remaining,lot.quantity)
            cost = None if lot.cost_usd is None else lot.cost_usd*take/lot.quantity
            removed.append(Lot(take,cost,lot.opened,lot.source,lot.basis_status))
            lot.quantity -= take
            if cost is not None:
                lot.cost_usd -= cost
            remaining -= take
            if abs(lot.quantity)<=EPS:
                self.lots[key].remove(lot)
        return removed, remaining

    def trade(self,key,quantity,acquisition_cost,at,source,status='documented'):
        """Cash is handled separately. Short receipts are never positive basis."""
        quantity = D(quantity)
        if quantity<0:
            removed,remainder = self.remove(key,-quantity)
            if remainder>EPS:
                self.add(key,-remainder,D(0),at,source,status)
            return removed
        original = quantity
        for lot in list(self.lots[key]):
            if lot.quantity>=0 or quantity<=EPS:
                continue
            close = min(quantity,-lot.quantity)
            lot.quantity += close
            quantity -= close
            if abs(lot.quantity)<=EPS:
                self.lots[key].remove(lot)
        if quantity>EPS:
            cost = None if acquisition_cost is None else acquisition_cost*quantity/original
            self.add(key,quantity,cost,at,source,status)
        return []

    def convert(self,old,new,quantity,ratio):
        removed,remaining = self.remove(old,quantity)
        for lot in removed:
            self.add(new,lot.quantity*ratio,lot.cost_usd,lot.opened,lot.source,lot.basis_status)
        return remaining
