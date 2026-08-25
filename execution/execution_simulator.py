"""execution/execution_simulator.py
Simulated market execution for PAPER TRADING only.

Simulates:
- reference price -> bid/ask spread
- slippage
- market impact (via execution/market_impact.py)
- partial fills for very large orders
- fees (maker/taker)
- execution delay (simulated timestamp)

Returns an ExecutionResult dataclass describing the fill.

Never executes real orders.
"""
from dataclasses import dataclass
from typing import Optional
import time
import math

from config import cfg
from execution.market_impact import default_impact


@dataclass
class ExecutionResult:
    symbol: str
    side: str  # 'BUY' or 'SELL'
    requested_qty: float
    executed_qty: float
    avg_price: float
    fees: float
    slippage_cost: float
    impact_cost: float
    total_cost: float
    partial: bool
    timestamp: float
    notes: Optional[str] = None


def simulate_market_order(symbol: str, qty: float, reference_price: float) -> ExecutionResult:
    """Simulate a market order execution.

    qty: signed base asset quantity (positive = buy, negative = sell)
    reference_price: current mid price
    """
    side = 'BUY' if qty > 0 else 'SELL'
    abs_qty = abs(qty)
    ts = time.time()

    # Defensive checks
    if reference_price <= 0 or abs_qty <= 0:
        return ExecutionResult(symbol, side, qty, 0.0, 0.0, 0.0, 0.0, 0.0, True, ts, notes='Invalid qty or price')

    # Spread model (symmetric)
    spread_pct = max(1e-6, float(cfg.SLIPPAGE))  # use SLIPPAGE as base spread/slippage estimate
    half_spread = reference_price * spread_pct / 2.0
    bid = reference_price - half_spread
    ask = reference_price + half_spread

    # Market impact
    impact = default_impact.estimate(qty, reference_price)
    impact_price = impact.impact_price

    # Execution base price (assume taker execution at worse side + impact)
    if side == 'BUY':
        base_exec_price = ask + impact_price
    else:
        base_exec_price = bid + impact_price  # impact_price may be negative for sells

    # Partial fill model: if order size >> liquidity, simulate partial fill
    liquidity = max(1e-9, float(cfg.MARKET_IMPACT.liquidity))
    partial = False
    if abs_qty > liquidity * 5:
        # very large => partial fill of some fraction
        fill_fraction = max(0.1, liquidity * 5 / abs_qty)
        executed_qty = abs_qty * fill_fraction
        partial = True
        notes = f"Partial fill ({executed_qty:.6f}/{abs_qty:.6f}) due to low liquidity"
    else:
        executed_qty = abs_qty
        notes = "Full fill"

    # Slippage cost (extra beyond spread and impact): model as random-ish fraction of spread; deterministic here
    slippage_per_unit = half_spread * 0.5  # conservative extra slippage
    slippage_cost = executed_qty * slippage_per_unit

    # Impact cost: impact_price * executed_qty
    impact_cost = executed_qty * impact_price

    # Average price (VWAP-like). For simplicity we use base_exec_price plus slippage per unit
    if side == 'BUY':
        avg_price = base_exec_price + (slippage_per_unit)
    else:
        avg_price = base_exec_price - (slippage_per_unit)

    # Fees (assume taker for market orders)
    fee_rate = float(cfg.FEES.taker)
    fees = executed_qty * avg_price * fee_rate

    # Total cost to trader (for BUY: cash outflow = executed_qty*avg_price + fees + slippage_cost + impact_cost)
    total_cost = executed_qty * avg_price + fees + slippage_cost + impact_cost

    # Return signed executed quantity
    executed_signed = executed_qty if qty > 0 else -executed_qty

    return ExecutionResult(
        symbol=symbol,
        side=side,
        requested_qty=qty,
        executed_qty=executed_signed,
        avg_price=avg_price,
        fees=fees,
        slippage_cost=slippage_cost,
        impact_cost=impact_cost,
        total_cost=total_cost,
        partial=partial,
        timestamp=time.time(),
        notes=notes
    )
