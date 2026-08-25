"""backtest/backtester.py
A minimal backtesting harness that uses the same execution simulator and portfolio APIs.
This backtester is intentionally simple: it steps through a provided timeline of prices per symbol
and at each timestamp it calls the strategy (generate_signal) and, if a signal passes R:R and sizing,
executes via the execution simulator and updates the portfolio.

For Phase 1 this is sufficient to run deterministic synthetic scenarios and to verify the
execution/risk/portfolio plumbing. It intentionally avoids any look-ahead: only candles up to
current index are provided to the strategy.
"""
from typing import Dict, List, Callable, Any
from datetime import datetime

from portfolio.account import Account
from execution.execution_simulator import simulate_market_order
from utilities.rr_engine import rr_is_valid, compute_sl_tp
from utilities.position_sizing import calculate_position_size
from persistence.storage import save_trade, save_run

# generate_signal lives in bot.py (we reuse the existing strategy)
from bot import generate_signal


class Backtester:
    def __init__(self, symbols: List[str], starting_balance: float = None):
        self.symbols = symbols
        self.account = Account(starting_balance or None)
        self.run_id = None

    def run_synthetic(self, synthetic_candles: Dict[str, List[Dict[str, Any]]]):
        """Run a deterministic synthetic backtest.

        synthetic_candles: dict mapping symbol -> list of candles where each candle is
            {'timestamp': int, 'open': float, 'high': float, 'low': float, 'close': float}
        Candles for all symbols must be the same length and aligned by index.
        """
        # Validate
        lengths = [len(v) for v in synthetic_candles.values()]
        if len(set(lengths)) != 1:
            raise ValueError('All symbol candle lists must have the same length')
        n = lengths[0]

        # Main loop: step through candles
        for i in range(n):
            # Prepare klines slices up to current index for each symbol
            price_map = {}
            klines_map = {}
            for s, candles in synthetic_candles.items():
                # We pass the full lists up to i+1 to the existing generate_signal (which expects lists of klines)
                klines_slice = candles[: i + 1]
                # convert to Binance-like klines structure minimally: [openTime, open, high, low, close, ...]
                binance_klines = []
                for c in klines_slice:
                    binance_klines.append([c['timestamp'], c['open'], c['high'], c['low'], c['close'], 0, 0, 0, 0, 0, 0, 0])
                klines_map[s] = binance_klines
                price_map[s] = klines_slice[-1]['close']

            # First, check SL/TP for existing positions and close if hit
            closed = self.account.check_sl_tp(price_map, simulate_market_order)
            for p in closed:
                # persist closed trade
                trade = self._position_to_trade_record(p)
                save_trade(trade)

            # Then generate signals and try to open new positions
            for s in self.symbols:
                current_price = price_map[s]
                # prepare klines for timeframes expected by generate_signal in bot.py (15m,1h,4h)
                # For synthetic we will pass same klines for all timeframes
                try:
                    signal = generate_signal(s, klines_map[s], klines_map[s], klines_map[s], current_price)
                except Exception:
                    continue

                if signal.direction == signal.direction.NO_TRADE or signal.confidence <= 0:
                    continue

                # compute SL/TP
                # risk distance (price units)
                risk_distance = abs(signal.entry - signal.stop_loss)
                if risk_distance <= 0:
                    continue

                if not rr_is_valid(signal.entry, signal.stop_loss, signal.take_profit):
                    continue

                # sizing
                size, risk_amount = calculate_position_size(self.account.equity, signal.entry, signal.stop_loss)
                if size <= 0:
                    continue

                # execute via simulator
                exec_res = simulate_market_order(s, size if signal.direction.name == 'LONG' else -size, current_price)
                if exec_res.executed_qty == 0:
                    continue

                # open position in account
                pos = self.account.open_position(s, signal.direction.name, exec_res.executed_qty, exec_res.avg_price,
                                                 signal.stop_loss, signal.take_profit, exec_res, {'risk_amount': risk_amount, 'signal_score': signal.signal_strength})
                # save trade entry placeholder (exit data will be filled when closed)
                if pos:
                    trade_record = self._position_to_trade_record(pos)
                    save_trade(trade_record)

        # At end, close remaining open positions at last prices
        final_price_map = {s: synthetic_candles[s][-1]['close'] for s in self.symbols}
        closed = self.account.check_sl_tp(final_price_map, simulate_market_order)
        for p in closed:
            save_trade(self._position_to_trade_record(p))

        # Save run summary
        run = {
            'start_time': datetime.utcfromtimestamp(synthetic_candles[self.symbols[0]][0]['timestamp']).isoformat() + 'Z',
            'end_time': datetime.utcfromtimestamp(synthetic_candles[self.symbols[0]][-1]['timestamp']).isoformat() + 'Z',
            'config_snapshot': {},
            'starting_balance': self.account.starting_balance,
            'ending_balance': self.account.current_balance,
            'total_pnl': self.account.realized_pnl,
            'max_drawdown': self.account.max_drawdown,
            'num_trades': len(self.account.positions)
        }
        run_id = save_run(run)
        self.run_id = run_id
        return run_id

    def _position_to_trade_record(self, p: Any) -> Dict:
        return {
            'run_id': self.run_id,
            'timestamp': datetime.utcfromtimestamp(p.open_time).isoformat() + 'Z',
            'symbol': p.symbol,
            'side': p.side,
            'entry_price': p.entry_price,
            'exit_price': p.exit_price,
            'quantity': p.quantity,
            'stop_loss': p.stop_loss,
            'take_profit': p.take_profit,
            'risk_amount': p.signal_meta.get('risk_amount'),
            'rr': cfg.RISK_REWARD,
            'signal_score': p.signal_meta.get('signal_score'),
            'market_regime': p.signal_meta.get('market_regime'),
            'gross_pnl': p.gross_pnl,
            'fees': p.fees,
            'slippage': p.slippage,
            'impact': p.impact,
            'net_pnl': p.net_pnl,
            'r_multiple': p.r_multiple,
            'exit_reason': p.exit_reason,
            'metadata': p.signal_meta
        }
