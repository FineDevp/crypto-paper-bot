"""portfolio/account.py
Multi-position simulated account with full P&L accounting and risk controls.

API (high-level):
- Account.open_position(symbol, side, qty, entry_price, stop_loss, take_profit, signal_meta)
- Account.close_position(position_id or object, exit_price, reason)
- Account.check_sl_tp(current_price_by_symbol)
- Account.get_summary()

Positions are stored with detailed fields: fees, slippage, impact, gross/net P&L, R multiple, etc.

This module uses config.cfg for defaults and hard safety limits.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict
import math

from config import cfg
from execution.execution_simulator import ExecutionResult


@dataclass
class Position:
    id: int
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    quantity: float  # signed (positive for long, negative for short)
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: float
    fees: float = 0.0
    slippage: float = 0.0
    impact: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    status: str = 'OPEN'  # OPEN, CLOSED
    close_time: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    r_multiple: Optional[float] = None
    signal_meta: Dict = field(default_factory=dict)


@dataclass
class Account:
    starting_balance: float = cfg.STARTING_BALANCE
    positions: List[Position] = field(default_factory=list)
    next_position_id: int = 1

    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    total_impact: float = 0.0
    current_balance: float = field(init=False)
    equity: float = field(init=False)

    trades_today: int = 0
    daily_loss: float = 0.0
    consecutive_losses: int = 0
    peak_equity: float = field(init=False)
    max_drawdown: float = 0.0

    max_positions: int = cfg.MAX_SIMULTANEOUS_POSITIONS

    def __post_init__(self):
        self.current_balance = self.starting_balance
        self.equity = self.starting_balance
        self.peak_equity = self.starting_balance

    # ------------------------ Position Management ------------------------
    def open_position(self, symbol: str, side: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: float, exec_result: ExecutionResult, signal_meta: Dict) -> Optional[Position]:
        """Open a position using results from execution_simulator (exec_result)."""
        # Check max positions
        open_count = len([p for p in self.positions if p.status == 'OPEN'])
        if open_count >= self.max_positions:
            return None

        pos = Position(
            id=self.next_position_id,
            symbol=symbol,
            side=side,
            quantity=exec_result.executed_qty,  # signed
            entry_price=exec_result.avg_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            open_time=exec_result.timestamp,
            fees=exec_result.fees,
            slippage=exec_result.slippage_cost,
            impact=exec_result.impact_cost,
            signal_meta=signal_meta
        )

        # Update account-level totals
        self.positions.append(pos)
        self.next_position_id += 1

        self.total_fees += exec_result.fees
        self.total_slippage += exec_result.slippage_cost
        self.total_impact += exec_result.impact_cost

        # Note: realized/unrealized PnL remains until closed
        self.trades_today += 1

        return pos

    def close_position(self, position: Position, exec_result: ExecutionResult, reason: str) -> Optional[Position]:
        """Close an open position using execution results."""
        if position.status != 'OPEN':
            return None

        # Compute P&L
        entry = position.entry_price
        exit_price = exec_result.avg_price
        qty = position.quantity

        if position.side == 'LONG' or qty > 0:
            gross = (exit_price - entry) * abs(qty)
        else:
            gross = (entry - exit_price) * abs(qty)

        fees = exec_result.fees
        slippage = exec_result.slippage_cost
        impact = exec_result.impact_cost

        net = gross - fees - slippage - impact

        position.exit_price = exit_price
        position.close_time = exec_result.timestamp
        position.status = 'CLOSED'
        position.exit_reason = reason
        position.gross_pnl = gross
        position.net_pnl = net
        position.fees += fees
        position.slippage += slippage
        position.impact += impact

        # R multiple: net / risk_amount (risk amount inferred from signal_meta if provided)
        risk_amount = position.signal_meta.get('risk_amount', None)
        if risk_amount and risk_amount > 0:
            position.r_multiple = net / risk_amount
        else:
            position.r_multiple = None

        # Update account totals
        self.realized_pnl += net
        self.total_fees += fees
        self.total_slippage += slippage
        self.total_impact += impact
        self.current_balance += net

        # Update consecutive losses
        if net < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Update peak equity and drawdown
        self.equity = self.current_balance + self.compute_unrealized_pnl()
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        drawdown = (self.peak_equity - self.equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        return position

    # ------------------------ Risk & Metrics ------------------------
    def compute_unrealized_pnl(self, price_map: Dict[str, float] = None) -> float:
        total = 0.0
        for p in self.positions:
            if p.status != 'OPEN':
                continue
            # get current price for symbol
            if price_map and p.symbol in price_map:
                current = price_map[p.symbol]
            else:
                current = p.entry_price
            if p.side == 'LONG' or p.quantity > 0:
                total += (current - p.entry_price) * abs(p.quantity)
            else:
                total += (p.entry_price - current) * abs(p.quantity)
        self.unrealized_pnl = total
        return total

    def compute_equity(self, price_map: Dict[str, float] = None) -> float:
        self.equity = self.current_balance + self.compute_unrealized_pnl(price_map)
        return self.equity

    def get_account_summary(self, price_map: Dict[str, float] = None) -> Dict:
        self.compute_equity(price_map)
        return {
            'starting_balance': self.starting_balance,
            'current_balance': self.current_balance,
            'equity': self.equity,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'total_fees': self.total_fees,
            'total_slippage': self.total_slippage,
            'total_impact': self.total_impact,
            'open_positions': [p for p in self.positions if p.status == 'OPEN'],
            'closed_positions': [p for p in self.positions if p.status == 'CLOSED'],
            'trades_today': self.trades_today,
            'consecutive_losses': self.consecutive_losses,
            'max_drawdown_pct': self.max_drawdown
        }

    # ------------------------ SL/TP checking ------------------------
    def check_sl_tp(self, price_map: Dict[str, float], execution_simulator_fn) -> List[Position]:
        """Check open positions and close if SL/TP or trailing-stop conditions met.

        execution_simulator_fn: callable(symbol, qty, reference_price) -> ExecutionResult
        Returns a list of closed positions
        """
        closed = []
        for p in list(self.positions):
            if p.status != 'OPEN':
                continue
            current_price = price_map.get(p.symbol, p.entry_price)

            if p.side == 'LONG':
                # SL
                if current_price <= p.stop_loss:
                    exec_res = execution_simulator_fn(p.symbol, -p.quantity, current_price)
                    closed_pos = self.close_position(p, exec_res, 'STOP_LOSS_HIT')
                    closed.append(closed_pos)
                    continue
                # TP
                if current_price >= p.take_profit:
                    exec_res = execution_simulator_fn(p.symbol, -p.quantity, current_price)
                    closed_pos = self.close_position(p, exec_res, 'TAKE_PROFIT_HIT')
                    closed.append(closed_pos)
            else:  # SHORT
                if current_price >= p.stop_loss:
                    exec_res = execution_simulator_fn(p.symbol, -p.quantity, current_price)
                    closed_pos = self.close_position(p, exec_res, 'STOP_LOSS_HIT')
                    closed.append(closed_pos)
                if current_price <= p.take_profit:
                    exec_res = execution_simulator_fn(p.symbol, -p.quantity, current_price)
                    closed_pos = self.close_position(p, exec_res, 'TAKE_PROFIT_HIT')
                    closed.append(closed_pos)

        return closed

