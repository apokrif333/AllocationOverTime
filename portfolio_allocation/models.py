from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)
EPS = Decimal('0.00000001')


def D(value=0) -> Decimal:
    return Decimal(str(value)) if value is not None and value != '' else ZERO


@dataclass
class Issue:
    severity: str
    code: str
    details: str
    sources: list[str] = field(default_factory=list)
    instrument: str = ''
    timestamp: str = ''


@dataclass
class Instrument:
    key: str
    name: str
    symbol: str = ''
    isin: str = ''
    asset_class: str = 'Other'
    currency: str = 'USD'
    multiplier: Decimal = Decimal(1)
    strike: Decimal | None = None
    option_type: str = ''
    expiry: str = ''
    underlying: str = ''
    is_option: bool = False
    futures_option: bool = False


@dataclass
class Event:
    timestamp: datetime
    kind: str
    key: str = ''
    currency: str = 'USD'
    quantity: Decimal = ZERO
    amount: Decimal = ZERO
    commission: Decimal = ZERO
    price: Decimal = ZERO
    sources: list[str] = field(default_factory=list)
    details: str = ''
    priority: int = 50
    row: int = 0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lot:
    quantity: Decimal
    cost_usd: Decimal | None
    opened: datetime
    source: str
    basis_status: str = 'documented'


@dataclass
class State:
    timestamp: datetime
    amounts: dict[str, float | None]
    weights: dict[str, float | None]
    quantities: dict[str, float]
    native_cash: dict[str, float]
    total_cash: float | None
    free_cash: float | None
    reserved: float
    borrowing: float | None
    denominator: float | None
    net_capital: float | None
    valid: bool
    basis_status: dict[str, str]
    fx_used: dict
    events: list[dict]
    warnings: list[str]
    last_events: dict[str, str]
