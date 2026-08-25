"""execution/market_impact.py
Parametric market-impact simulation (square-root law + optional decay).
This is a simulation helper: it estimates immediate impact (price ticks and absolute price)
for a given order size relative to a liquidity normalization.

All parameters are configurable via config.cfg.MARKET_IMPACT
"""
from dataclasses import dataclass
import math
import time
from typing import NamedTuple

from config import cfg


class ImpactEstimate(NamedTuple):
    impact_ticks: float
    impact_price: float
    impact_pct: float
    execution_price: float
    timestamp: float


@dataclass
class MarketImpact:
    """Parametric market-impact model.

    Formula (parametric): impact_ticks = k * (|qty| / liquidity)**alpha
    execution_price = reference_price + sign(qty) * impact_ticks * tick_size
    current impact decays exponentially (if decay_tau_sec > 0) when re-used across orders.
    """

    def __init__(self, cfg_market_impact=None):
        self.cfg = cfg_market_impact or cfg.MARKET_IMPACT
        self.current_impact_ticks = 0.0
        self.last_ts = time.time()

    def _decay(self):
        now = time.time()
        dt = max(0.0, now - self.last_ts)
        tau = max(1.0, float(self.cfg.decay_tau_sec))
        decay_factor = math.exp(-dt / tau)
        self.current_impact_ticks *= decay_factor
        self.last_ts = now

    def estimate(self, qty: float, reference_price: float) -> ImpactEstimate:
        """Estimate impact for an instantaneous market order of size qty (signed).

        qty: signed quantity in base units (positive = buy, negative = sell)
        reference_price: current mid or bid/ask reference price
        """
        self._decay()
        if qty == 0 or reference_price <= 0:
            return ImpactEstimate(0.0, 0.0, 0.0, reference_price, time.time())

        L = max(1e-9, float(self.cfg.liquidity))
        k = float(self.cfg.k)
        alpha = float(self.cfg.alpha)
        tick = float(self.cfg.tick_size)
        max_ticks = int(self.cfg.max_ticks)

        normalized = abs(qty) / L
        impact_ticks = k * (normalized ** alpha)
        # round to nearest tick but keep fractional for accumulation
        impact_ticks = max(0.0, impact_ticks)

        signed_ticks = math.copysign(impact_ticks, qty)

        # accumulate and clamp
        self.current_impact_ticks += signed_ticks
        if self.current_impact_ticks > max_ticks:
            self.current_impact_ticks = max_ticks
        if self.current_impact_ticks < -max_ticks:
            self.current_impact_ticks = -max_ticks

        impact_price = self.current_impact_ticks * tick
        execution_price = reference_price + impact_price
        impact_pct = impact_price / reference_price if reference_price != 0 else 0.0

        return ImpactEstimate(self.current_impact_ticks, impact_price, impact_pct, execution_price, time.time())


# Convenience constructor
default_impact = MarketImpact()
