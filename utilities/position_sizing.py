"""utilities/position_sizing.py
Risk-based position sizing utilities.
"""
from decimal import Decimal, ROUND_DOWN
from typing import Tuple

from config import cfg


def round_down(value: float, step: float) -> float:
    """Round down value to nearest multiple of step."""
    if step <= 0:
        return value
    q = Decimal(str(value))
    s = Decimal(str(step))
    rounded = (q // s) * s
    return float(rounded)


def calculate_position_size(equity: float, entry_price: float, stop_loss: float,
                            lot_size: float = None, min_qty: float = None,
                            max_qty: float = None, min_notional: float = None) -> Tuple[float, float]:
    """Calculate position size (base asset quantity) given equity and stop loss.

    Returns (position_size, risk_amount)
    - position_size is rounded down to lot_size and will respect min_qty, max_qty and min_notional
    - risk_amount = equity * RISK_PER_TRADE
    """
    if lot_size is None:
        lot_size = float(Decimal(str(cfg.MARKET_IMPACT.tick_size)))  # fallback
    if min_qty is None:
        min_qty = float(cfg.MARKET_IMPACT.tick_size) * 0.0001
    if max_qty is None:
        max_qty = 1e9
    if min_notional is None:
        min_notional = float(Decimal(os_min_notional())) if os_min_notional() else 10.0

    # Defensive checks
    if entry_price <= 0 or stop_loss <= 0:
        return 0.0, 0.0

    # Risk amount in quote currency
    risk_amount = equity * float(cfg.RISK_PER_TRADE)

    # Distance in price units
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return 0.0, 0.0

    # Position size in base units before rounding
    raw_size = risk_amount / stop_distance

    # Ensure notional size meets min_notional (quote value = size * entry_price)
    raw_notional = raw_size * entry_price
    if raw_notional < min_notional:
        # bump size to meet min_notional but that increases risk; instead return zero to be safe
        return 0.0, risk_amount

    # Round down to lot size
    size = round_down(raw_size, lot_size)

    # Clamp
    if size < min_qty:
        return 0.0, risk_amount
    if size > max_qty:
        size = max_qty

    # Final check: ensure risk_amount is not exceeded due to rounding up (we rounded down so safe)
    return float(size), float(risk_amount)


def os_min_notional():
    """Read MIN_NOTIONAL from env if present; helper to avoid importing os at top-level for tests.
    Returns string or None."""
    try:
        import os
        return os.getenv('MIN_NOTIONAL', None)
    except Exception:
        return None
