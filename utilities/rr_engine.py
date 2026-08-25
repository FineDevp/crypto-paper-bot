"""utilities/rr_engine.py
Risk/Reward utilities. Enforce minimum R:R and compute SL/TP for LONG/SHORT.
"""
from typing import Tuple
from config import cfg


def compute_sl_tp(entry_price: float, risk_distance: float, direction: str) -> Tuple[float, float]:
    """Given entry price and risk_distance (in price units), compute (stop_loss, take_profit).

    direction: 'LONG' or 'SHORT'
    """
    if direction == 'LONG':
        stop = entry_price - abs(risk_distance)
        tp = entry_price + abs(risk_distance) * cfg.RISK_REWARD
    else:
        stop = entry_price + abs(risk_distance)
        tp = entry_price - abs(risk_distance) * cfg.RISK_REWARD
    return stop, tp


def rr_is_valid(entry_price: float, stop_loss: float, take_profit: float) -> bool:
    """Return True if the R:R between stop_loss and take_profit meets cfg.RISK_REWARD.

    For LONG: risk = entry - stop; reward = tp - entry
    For SHORT: risk = stop - entry; reward = entry - tp
    """
    if stop_loss == entry_price or take_profit == entry_price:
        return False

    # Determine direction
    direction = 'LONG' if take_profit > entry_price else 'SHORT'

    if direction == 'LONG':
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
    else:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit

    if risk <= 0:
        return False

    rr = reward / risk
    return rr >= float(cfg.RISK_REWARD)
