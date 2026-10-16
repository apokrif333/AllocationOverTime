"""Cash-secured collateral estimates; never broker margin or new cash."""
from .models import D, EPS
from .fx import MissingFX


def collateral(fifo,instruments,fx,at,total_cash,policy='cash-secured-puts'):
    available = max(D(total_cash),D())
    allocated,requirements,warnings = {},{},[]
    for key in sorted(instruments):
        inst = instruments[key]
        qty = fifo.quantity(key)
        if qty>=-EPS:
            continue
        reliable = inst.is_option and inst.option_type=='P' and not inst.futures_option and inst.strike is not None and inst.multiplier>0
        if policy=='none' or not reliable:
            warnings.append(f'Uncovered short exposure: {inst.name}; no reliable configured collateral estimate')
            continue
        try:
            required = fx.usd(abs(qty)*inst.strike*inst.multiplier,inst.currency,at)
        except MissingFX as exc:
            warnings.append(f'Uncovered {inst.name}: {exc}')
            continue
        reserved = min(required,available)
        allocated[key] = reserved
        requirements[key] = required
        available -= reserved
        if required-reserved>EPS:
            warnings.append(f'Insufficient cash for {inst.name}: estimated cash-secured collateral {required:.2f} USD, reserved {reserved:.2f} USD')
    return allocated,requirements,warnings
