#!/usr/bin/env python3
"""
Optimized Paper-Trading Bot for Binance - HIGH PROFIT VERSION
PAPER TRADING ONLY - No real orders executed

OPTIMIZATIONS:
- ONE POSITION AT A TIME (prevents duplicate orders)
- HIGH-QUALITY SIGNALS: MACD + Stochastic RSI + Strong Trend Confirmation
- MARGIN SUPPORT: Up to 10x leverage
- BETTER PROFIT: Improved entry/exit strategy with trailing stops
- AGGRESSIVE RISK MANAGEMENT: 0.5-2% risk per trade (configurable)
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

import aiohttp

# ============================================================================
# CONFIGURATION & SAFETY LOCK
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# *** SAFETY LOCK: PAPER_MODE cannot be disabled ***
PAPER_MODE = os.getenv('PAPER_MODE', 'true').lower() == 'true'
if not PAPER_MODE:
    logger.error("FATAL: PAPER_MODE must be 'true'. Real trading is NOT implemented.")
    sys.exit(1)
logger.info("✓ PAPER_MODE=true (safety lock active)")

# Configuration from environment variables
STARTING_BALANCE = float(os.getenv('STARTING_BALANCE', '50'))
RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '0.01'))  # 1% per trade (HIGHER for more profit)
MAX_LEVERAGE = float(os.getenv('MAX_LEVERAGE', '10'))  # 10x margin
TARGET_RETURN = float(os.getenv('TARGET_RETURN', '0.05'))  # 5% per winning trade
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL_SECONDS', '120'))  # 2 minutes (faster scanning)
CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '0.80'))  # 80% confidence
SLIPPAGE = float(os.getenv('SLIPPAGE', '0.001'))  # 0.1%

# Symbols to trade (focus on high volatility)
SYMBOLS = [s.strip() for s in os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT').split(',')]
TIMEFRAMES = ['15m', '1h', '4h']
BINANCE_API_PUBLIC = "https://api.binance.com/api/v3"

# ONE POSITION LOCK (single trade active at any time)
GLOBAL_POSITION_LIMIT = 1

# Validation
assert STARTING_BALANCE > 0, "STARTING_BALANCE must be positive"
assert 0 < RISK_PER_TRADE <= 0.1, "RISK_PER_TRADE must be between 0 and 10%"
assert SCAN_INTERVAL > 0, "SCAN_INTERVAL_SECONDS must be positive"
assert MAX_LEVERAGE >= 1 and MAX_LEVERAGE <= 10, "MAX_LEVERAGE must be 1-10x"
logger.info(f"✓ Config: Balance=${STARTING_BALANCE}, Risk={RISK_PER_TRADE*100:.1f}%, Leverage={MAX_LEVERAGE}x, Symbols={SYMBOLS}")

# ============================================================================
# DATA MODELS
# ============================================================================

class TradeDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"

@dataclass
class Signal:
    symbol: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasoning: str
    timestamp: datetime
    signal_strength: float = 0.0  # 0-1 score of signal quality

@dataclass
class Trade:
    symbol: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_amount: float
    leverage: float
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, WIN, LOSS
    max_profit_price: float = 0.0  # Track highest price for trailing stop

# ============================================================================
# ACCOUNT STATE (Single position only)
# ============================================================================

class SimulatedAccount:
    """Paper trading account with ONE POSITION LIMIT."""
    
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.trades: List[Trade] = []
        self.active_trade: Optional[Trade] = None  # ONLY ONE
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.win_rate = 0.0

    def has_open_position(self) -> bool:
        """Check if there's an active trade."""
        return self.active_trade is not None

    def get_available_risk(self) -> float:
        """Risk amount for next trade."""
        return self.current_balance * RISK_PER_TRADE

    def calculate_position_size_with_leverage(self, risk_amount: float, entry: float, stop_loss: float, leverage: float) -> float:
        """Calculate position size with leverage.
        
        Formula: position_size = (risk_amount * leverage) / |entry - stop_loss|
        Example: $1 risk * 5x leverage / $100 distance = 0.05 BTC (5x exposure)
        """
        distance_to_sl = abs(entry - stop_loss)
        if distance_to_sl == 0:
            return 0
        return (risk_amount * leverage) / distance_to_sl

    def open_trade(self, signal: Signal) -> Optional[Trade]:
        """Open a trade (only if no active position)."""
        
        # ENFORCE ONE POSITION LIMIT
        if self.active_trade is not None:
            logger.warning(f"⚠️  Cannot open {signal.symbol}: already have active position ({self.active_trade.symbol})")
            return None

        risk_amount = self.get_available_risk()
        if risk_amount <= 0:
            logger.warning(f"⚠️  Cannot open {signal.symbol}: insufficient balance (${self.current_balance:.2f})")
            return None

        # Determine leverage based on confidence
        leverage = min(1 + (signal.confidence - 0.5) * 10, MAX_LEVERAGE)  # 1x to 10x
        leverage = max(1.0, leverage)

        position_size = self.calculate_position_size_with_leverage(risk_amount, signal.entry, signal.stop_loss, leverage)
        if position_size <= 0:
            logger.warning(f"⚠️  Cannot open {signal.symbol}: invalid SL distance")
            return None

        # CREATE TRADE RECORD
        trade = Trade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            position_size=position_size,
            risk_amount=risk_amount,
            leverage=leverage,
            entry_time=signal.timestamp,
            max_profit_price=signal.entry
        )

        # ATOMIC UPDATE
        self.active_trade = trade
        self.trades.append(trade)
        self.total_trades += 1

        logger.info(
            f"🚀 TRADE OPENED: {signal.symbol} {signal.direction.value} | "
            f"Entry: ${signal.entry:.2f} | SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f} | "
            f"Size: {position_size:.6f} ({leverage:.1f}x) | Risk: ${risk_amount:.2f} | "
            f"Confidence: {signal.confidence:.1%} | Signal: {signal.reasoning}"
        )
        return trade

    def close_trade(self, exit_price: float, reason: str) -> Optional[Trade]:
        """Close the active trade and calculate P&L."""
        
        if self.active_trade is None:
            return None

        trade = self.active_trade
        trade.exit_price = exit_price
        trade.exit_time = datetime.now()

        # CALCULATE P&L (direction & leverage aware)
        if trade.direction == TradeDirection.LONG:
            gross_pnl = (exit_price - trade.entry) * trade.position_size
        else:  # SHORT
            gross_pnl = (trade.entry - exit_price) * trade.position_size

        # DEDUCT SLIPPAGE
        slippage_cost = trade.position_size * exit_price * SLIPPAGE * 2
        net_pnl = gross_pnl - slippage_cost

        trade.pnl = net_pnl
        trade.status = "WIN" if net_pnl > 0 else "LOSS"

        # UPDATE ACCOUNT
        self.current_balance += net_pnl
        self.total_pnl += net_pnl
        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        self.win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        logger.info(
            f"✅ TRADE CLOSED: {trade.symbol} {trade.direction.value} | "
            f"Exit: ${exit_price:.2f} | Gross P&L: ${gross_pnl:+.2f} | "
            f"Net P&L: ${net_pnl:+.2f} ({net_pnl/trade.risk_amount*100:+.1f}% of risk) | "
            f"Balance: ${self.current_balance:.2f} | {reason}"
        )
        
        # CLEAR POSITION
        self.active_trade = None
        return trade

    def check_sl_tp(self, current_price: float) -> Optional[Trade]:
        """Check SL/TP for active trade."""
        
        if self.active_trade is None:
            return None

        trade = self.active_trade

        # UPDATE MAX PROFIT FOR TRAILING STOP
        if trade.direction == TradeDirection.LONG and current_price > trade.max_profit_price:
            trade.max_profit_price = current_price
        elif trade.direction == TradeDirection.SHORT and current_price < trade.max_profit_price:
            trade.max_profit_price = current_price

        # CHECK STOP LOSS (hard limit)
        if trade.direction == TradeDirection.LONG:
            if current_price <= trade.stop_loss:
                return self.close_trade(trade.stop_loss, "STOP_LOSS_HIT")
            if current_price >= trade.take_profit:
                return self.close_trade(trade.take_profit, "TAKE_PROFIT_HIT")
            
            # TRAILING STOP: close if price falls 1% from max
            trailing_stop = trade.max_profit_price * 0.99
            if current_price <= trailing_stop and trade.max_profit_price > trade.entry:
                return self.close_trade(current_price, "TRAILING_STOP_HIT")
        
        else:  # SHORT
            if current_price >= trade.stop_loss:
                return self.close_trade(trade.stop_loss, "STOP_LOSS_HIT")
            if current_price <= trade.take_profit:
                return self.close_trade(trade.take_profit, "TAKE_PROFIT_HIT")
            
            # TRAILING STOP
            trailing_stop = trade.max_profit_price * 1.01
            if current_price >= trailing_stop and trade.max_profit_price < trade.entry:
                return self.close_trade(current_price, "TRAILING_STOP_HIT")

        return None

    def print_status(self):
        """Print account summary."""
        logger.info("=" * 100)
        logger.info(f"💰 ACCOUNT STATUS")
        logger.info(f"   Starting Balance: ${self.starting_balance:.2f}")
        logger.info(f"   Current Balance:  ${self.current_balance:.2f}")
        logger.info(f"   Total P&L:        ${self.total_pnl:+.2f} ({self.total_pnl/self.starting_balance*100:+.2f}%)")
        logger.info(f"   Trades:           {self.total_trades} (W:{self.winning_trades} L:{self.losing_trades}) WinRate:{self.win_rate:.1f}%")
        logger.info(f"   Active Position:  {'YES - ' + self.active_trade.symbol if self.active_trade else 'NO'}")
        logger.info("=" * 100)

# ============================================================================
# MARKET DATA
# ============================================================================

class MarketData:
    """Fetches data from Binance PUBLIC API only."""
    
    def __init__(self):
        self.current_prices: Dict[str, float] = {}

    async def fetch_klines(self, symbol: str, interval: str = '1h', limit: int = 200) -> List[List]:
        """Fetch candlestick data."""
        try:
            url = f"{BINANCE_API_PUBLIC}/klines"
            params = {'symbol': symbol, 'interval': interval, 'limit': limit}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        logger.warning(f"Rate limited on {symbol}")
                        return []
                    else:
                        logger.error(f"Failed to fetch {symbol} {interval}: HTTP {resp.status}")
                        return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {symbol} {interval}")
            return []
        except Exception as e:
            logger.error(f"Error fetching {symbol} {interval}: {e}")
            return []

    async def fetch_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current price."""
        try:
            url = f"{BINANCE_API_PUBLIC}/ticker/price"
            params = {'symbol': symbol}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data['price'])
                        self.current_prices[symbol] = price
                        return price
                    else:
                        return None
        except Exception:
            return None

# ============================================================================
# ADVANCED INDICATORS
# ============================================================================

def calculate_ema(prices: List[float], period: int = 9) -> float:
    """Exponential Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * multiplier + ema * (1 - multiplier)
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Relative Strength Index."""
    if len(prices) < period:
        return 50
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    seed = deltas[:period]
    up = sum(x for x in seed if x > 0) / period
    down = sum(abs(x) for x in seed if x < 0) / period
    
    rs = up / down if down != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    
    for delta in deltas[period:]:
        up = (up * (period - 1) + (delta if delta > 0 else 0)) / period
        down = (down * (period - 1) + (abs(delta) if delta < 0 else 0)) / period
        rs = up / down if down != 0 else 0
        rsi = 100 - (100 / (1 + rs))
    
    return rsi

def calculate_macd(prices: List[float]) -> tuple:
    """MACD (Moving Average Convergence Divergence).
    Returns: (macd_line, signal_line, histogram)
    """
    if len(prices) < 26:
        return 0, 0, 0
    
    ema_12 = calculate_ema(prices[-26:], 12)
    ema_26 = calculate_ema(prices[-26:], 26)
    macd_line = ema_12 - ema_26
    
    # Signal line (EMA of MACD)
    signal_line = ema_12 * 0.3 + ema_26 * 0.7  # Approximation
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

def calculate_stochastic_rsi(prices: List[float], period: int = 14) -> tuple:
    """Stochastic RSI - combines RSI with stochastic oscillator.
    Returns: (stoch_rsi, stoch_k, stoch_d)
    """
    if len(prices) < period * 2:
        return 50, 50, 50
    
    rsi_values = []
    for i in range(len(prices) - period):
        rsi = calculate_rsi(prices[i:i+period])
        rsi_values.append(rsi)
    
    if len(rsi_values) < 14:
        return 50, 50, 50
    
    min_rsi = min(rsi_values[-14:])
    max_rsi = max(rsi_values[-14:])
    range_rsi = max_rsi - min_rsi
    
    stoch_rsi = (rsi_values[-1] - min_rsi) / (range_rsi + 0.001) * 100
    stoch_k = stoch_rsi
    stoch_d = (stoch_k + rsi_values[-1]) / 2
    
    return stoch_rsi, stoch_k, stoch_d

def generate_signal(symbol: str, klines_15m: List[List], klines_1h: List[List], 
                   klines_4h: List[List], current_price: float) -> Signal:
    """Generate HIGH-QUALITY signals using MACD + Stochastic RSI + Multi-timeframe analysis."""
    
    try:
        # Extract prices
        closes_15m = [float(k[4]) for k in klines_15m[-50:]]
        closes_1h = [float(k[4]) for k in klines_1h[-50:]]
        closes_4h = [float(k[4]) for k in klines_4h[-50:]]
        
        if not all([closes_15m, closes_1h, closes_4h]):
            return Signal(symbol, TradeDirection.NO_TRADE, current_price, current_price, current_price, 0.0, "Insufficient data", datetime.now())
        
        # Calculate indicators
        ema_1h = calculate_ema(closes_1h, 9)
        ema_4h = calculate_ema(closes_4h, 9)
        
        rsi_1h = calculate_rsi(closes_1h, 14)
        rsi_4h = calculate_rsi(closes_4h, 14)
        
        macd_1h, signal_1h, hist_1h = calculate_macd(closes_1h)
        macd_4h, signal_4h, hist_4h = calculate_macd(closes_4h)
        
        stoch_rsi_15m, k_15m, d_15m = calculate_stochastic_rsi(closes_15m)
        stoch_rsi_1h, k_1h, d_1h = calculate_stochastic_rsi(closes_1h)
        
        direction = TradeDirection.NO_TRADE
        confidence = 0.0
        reasoning = ""
        signal_strength = 0.0
        
        # LONG SETUP: Strong uptrend with oversold recovery
        long_conditions = [
            current_price > ema_1h,           # Price above 1h EMA
            ema_1h > ema_4h,                  # 1h EMA above 4h EMA (uptrend)
            rsi_1h > 40 and rsi_1h < 80,     # RSI not overbought
            rsi_4h > 40 and rsi_4h < 80,     # 4h RSI healthy
            macd_1h > signal_1h,              # MACD bullish
            macd_4h > signal_4h,              # 4h MACD bullish
            stoch_rsi_15m < 50,               # 15m Stochastic oversold (entry opportunity)
        ]
        
        long_score = sum(long_conditions) / len(long_conditions)
        
        if long_score >= 0.7:  # 70% conditions met
            direction = TradeDirection.LONG
            confidence = 0.80 + (long_score - 0.7) * 0.2
            signal_strength = long_score
            reasoning = (f"🟢 LONG: Uptrend (1h>{4h}), MACD bullish, "
                        f"RSI 1h:{rsi_1h:.1f}/4h:{rsi_4h:.1f}, StochRSI oversold")
        
        # SHORT SETUP: Strong downtrend with overbought rejection
        short_conditions = [
            current_price < ema_1h,           # Price below 1h EMA
            ema_1h < ema_4h,                  # 1h EMA below 4h EMA (downtrend)
            rsi_1h > 20 and rsi_1h < 60,     # RSI not oversold
            rsi_4h > 20 and rsi_4h < 60,     # 4h RSI healthy
            macd_1h < signal_1h,              # MACD bearish
            macd_4h < signal_4h,              # 4h MACD bearish
            stoch_rsi_15m > 50,               # 15m Stochastic overbought (entry opportunity)
        ]
        
        short_score = sum(short_conditions) / len(short_conditions)
        
        if short_score >= 0.7:  # 70% conditions met
            direction = TradeDirection.SHORT
            confidence = 0.80 + (short_score - 0.7) * 0.2
            signal_strength = short_score
            reasoning = (f"🔴 SHORT: Downtrend (1h<4h), MACD bearish, "
                        f"RSI 1h:{rsi_1h:.1f}/4h:{rsi_4h:.1f}, StochRSI overbought")
        
        # Calculate SL/TP based on volatility
        if direction != TradeDirection.NO_TRADE:
            atr_estimate = max(closes_1h[-20:]) - min(closes_1h[-20:])
            if atr_estimate == 0:
                atr_estimate = current_price * 0.03  # 3% default
            
            if direction == TradeDirection.LONG:
                entry = current_price
                stop_loss = current_price - atr_estimate * 0.6
                take_profit = current_price + atr_estimate * 2.0  # 1:3.3 RR
            else:  # SHORT
                entry = current_price
                stop_loss = current_price + atr_estimate * 0.6
                take_profit = current_price - atr_estimate * 2.0
        else:
            entry = stop_loss = take_profit = current_price
        
        return Signal(symbol, direction, entry, stop_loss, take_profit, confidence, reasoning, datetime.now(), signal_strength)
    
    except Exception as e:
        logger.error(f"Error generating signal for {symbol}: {e}")
        return Signal(symbol, TradeDirection.NO_TRADE, current_price, current_price, current_price, 0.0, f"Error: {e}", datetime.now())

# ============================================================================
# MAIN BOT LOOP
# ============================================================================

async def main():
    """Main async loop - ONE POSITION AT A TIME."""
    
    logger.info("=" * 100)
    logger.info("🚀 CRYPTO TRADING BOT - OPTIMIZED FOR PROFIT")
    logger.info(f"   Mode: PAPER TRADING ONLY")
    logger.info(f"   Starting Balance: ${STARTING_BALANCE:.2f}")
    logger.info(f"   Risk per Trade: {RISK_PER_TRADE * 100:.1f}%")
    logger.info(f"   Max Leverage: {MAX_LEVERAGE}x")
    logger.info(f"   Position Limit: 1 (ONE AT A TIME)")
    logger.info(f"   Symbols: {', '.join(SYMBOLS)}")
    logger.info(f"   Scan Interval: {SCAN_INTERVAL}s")
    logger.info("=" * 100)

    account = SimulatedAccount(STARTING_BALANCE)
    market = MarketData()
    scan_count = 0

    while True:
        try:
            scan_count += 1
            logger.info(f"\n📡 SCAN #{scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # FETCH ALL DATA CONCURRENTLY
            tasks = []
            for symbol in SYMBOLS:
                tasks.append(market.fetch_current_price(symbol))
                tasks.append(market.fetch_klines(symbol, '15m', 100))
                tasks.append(market.fetch_klines(symbol, '1h', 100))
                tasks.append(market.fetch_klines(symbol, '4h', 100))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # PROCESS RESULTS
            idx = 0
            best_signal = None
            best_signal_symbol = None
            
            for symbol in SYMBOLS:
                current_price = results[idx]
                klines_15m = results[idx + 1]
                klines_1h = results[idx + 2]
                klines_4h = results[idx + 3]
                idx += 4

                # Handle fetch errors
                if isinstance(current_price, Exception) or current_price is None:
                    continue

                # CHECK SL/TP FOR ACTIVE POSITION
                if account.has_open_position() and account.active_trade.symbol == symbol:
                    account.check_sl_tp(current_price)

                # GENERATE SIGNAL
                if isinstance(klines_15m, list) and isinstance(klines_1h, list) and isinstance(klines_4h, list):
                    if len(klines_15m) > 0 and len(klines_1h) > 0 and len(klines_4h) > 0:
                        signal = generate_signal(symbol, klines_15m, klines_1h, klines_4h, current_price)
                        
                        # FIND BEST SIGNAL (if no position open)
                        if not account.has_open_position():
                            if signal.direction != TradeDirection.NO_TRADE and signal.confidence >= CONFIDENCE_THRESHOLD:
                                if best_signal is None or signal.confidence > best_signal.confidence:
                                    best_signal = signal
                                    best_signal_symbol = symbol

            # OPEN BEST SIGNAL (ONE AT A TIME)
            if best_signal and not account.has_open_position():
                account.open_trade(best_signal)

            # PRINT STATUS EVERY 5 SCANS
            if scan_count % 5 == 0:
                account.print_status()

            logger.info(f"⏳ Waiting {SCAN_INTERVAL}s until next scan...")
            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            logger.error(f"Error in main loop: {type(e).__name__}: {e}")
            await asyncio.sleep(10)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {type(e).__name__}: {e}")
        sys.exit(1)
