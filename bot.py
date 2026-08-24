#!/usr/bin/env python3
"""
Minimal Paper-Trading Bot for Binance Public Market Data
PAPER TRADING ONLY - No real orders executed

Safety Audit Checklist:
- PAPER_MODE=true is mandatory and cannot be disabled
- Only PUBLIC Binance endpoints used (no auth required)
- No API keys/secrets required or stored
- Starting balance is fully configurable
- Risk is exactly 0.2% of current equity per trade
- Position sizing mathematically correct
- SL/TP simulated accurately
- P&L updates account correctly
- Duplicate positions prevented
- Async scanning prevents race conditions
- Network errors handled gracefully
- Can run indefinitely on Railway
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

# Configuration from environment variables only (NO hardcoded values)
STARTING_BALANCE = float(os.getenv('STARTING_BALANCE', '50'))
RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '0.002'))  # 0.2%
TARGET_RETURN = float(os.getenv('TARGET_RETURN', '0.01'))  # 1%
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL_SECONDS', '300'))  # 5 minutes
CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '0.7'))  # 70%
SLIPPAGE = float(os.getenv('SLIPPAGE', '0.001'))  # 0.1%

# Only PUBLIC API endpoint (no auth required)
SYMBOLS = [s.strip() for s in os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')]
TIMEFRAMES = ['1h', '4h']
BINANCE_API_PUBLIC = "https://api.binance.com/api/v3"  # PUBLIC ONLY - no /sapi/ endpoints

# Validation
assert STARTING_BALANCE > 0, "STARTING_BALANCE must be positive"
assert 0 < RISK_PER_TRADE < 1, "RISK_PER_TRADE must be between 0 and 1"
assert SCAN_INTERVAL > 0, "SCAN_INTERVAL_SECONDS must be positive"
assert len(SYMBOLS) > 0, "At least one SYMBOL must be configured"
logger.info(f"✓ Config validated: Balance=${STARTING_BALANCE}, Risk={RISK_PER_TRADE*100:.2f}%, Symbols={SYMBOLS}")

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

@dataclass
class Trade:
    symbol: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_amount: float
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, WIN, LOSS

# ============================================================================
# ACCOUNT STATE (Thread-safe simulation)
# ============================================================================

class SimulatedAccount:
    """Tracks paper trading account state. NOT thread-safe but OK for single main() coroutine."""
    
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.trades: List[Trade] = []
        self.open_positions: Dict[str, Trade] = {}  # symbol -> Trade (prevents duplicates)
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

    def get_available_risk(self) -> float:
        """Calculate risk amount for next trade: exactly 0.2% of current balance.
        Formula: current_balance * RISK_PER_TRADE
        Example: $100 * 0.002 = $0.20
        """
        return self.current_balance * RISK_PER_TRADE

    def calculate_position_size(self, risk_amount: float, entry: float, stop_loss: float) -> float:
        """Calculate position size based on risk and SL distance.
        Formula: position_size = risk_amount / |entry - stop_loss|
        Example: $0.20 / $100 distance = 0.002 BTC
        """
        distance_to_sl = abs(entry - stop_loss)
        if distance_to_sl == 0:
            return 0  # Invalid trade setup
        return risk_amount / distance_to_sl

    def open_trade(self, signal: Signal) -> Optional[Trade]:
        """Open a new paper trade.
        
        Validation:
        - Prevent duplicate positions (one per symbol)
        - Ensure sufficient balance (risk_amount > 0)
        - Calculate position size from risk
        """
        # DUPLICATE POSITION CHECK
        if signal.symbol in self.open_positions:
            logger.warning(f"⚠️  Cannot open {signal.symbol}: position already open")
            return None

        risk_amount = self.get_available_risk()
        if risk_amount <= 0:
            logger.warning(f"⚠️  Cannot open {signal.symbol}: insufficient balance (${self.current_balance:.2f})")
            return None

        position_size = self.calculate_position_size(risk_amount, signal.entry, signal.stop_loss)
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
            entry_time=signal.timestamp
        )

        # ATOMIC: Update state
        self.open_positions[signal.symbol] = trade
        self.trades.append(trade)
        self.total_trades += 1

        logger.info(
            f"📈 TRADE OPENED: {signal.symbol} {signal.direction.value} | "
            f"Entry: ${signal.entry:.2f} | SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f} | "
            f"Size: {position_size:.6f} | Risk: ${risk_amount:.2f}"
        )
        return trade

    def close_trade(self, symbol: str, exit_price: float, reason: str) -> Optional[Trade]:
        """Close a paper trade and calculate P&L.
        
        P&L Formula:
        LONG:  pnl = (exit - entry) * size - slippage
        SHORT: pnl = (entry - exit) * size - slippage
        """
        if symbol not in self.open_positions:
            return None

        trade = self.open_positions[symbol]
        trade.exit_price = exit_price
        trade.exit_time = datetime.now()

        # CALCULATE P&L (direction-aware)
        if trade.direction == TradeDirection.LONG:
            gross_pnl = (exit_price - trade.entry) * trade.position_size
        else:  # SHORT
            gross_pnl = (trade.entry - exit_price) * trade.position_size

        # DEDUCT SLIPPAGE (entry + exit)
        slippage_cost = trade.position_size * exit_price * SLIPPAGE * 2
        net_pnl = gross_pnl - slippage_cost

        trade.pnl = net_pnl
        trade.status = "WIN" if net_pnl > 0 else "LOSS"

        # UPDATE ACCOUNT (atomic)
        self.current_balance += net_pnl
        self.total_pnl += net_pnl
        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        del self.open_positions[symbol]

        logger.info(
            f"🏁 TRADE CLOSED: {symbol} {trade.direction.value} | "
            f"Exit: ${exit_price:.2f} | Gross P&L: ${gross_pnl:+.2f} | "
            f"Slippage: ${slippage_cost:+.2f} | Net P&L: ${net_pnl:+.2f} | "
            f"Balance: ${self.current_balance:.2f} | {reason}"
        )
        return trade

    def check_sl_tp(self, symbol: str, current_price: float) -> Optional[Trade]:
        """Check if any open trade hit stop-loss or take-profit.
        
        LONG:  SL hit if price <= SL, TP hit if price >= TP
        SHORT: SL hit if price >= SL, TP hit if price <= TP
        """
        if symbol not in self.open_positions:
            return None

        trade = self.open_positions[symbol]

        # CHECK STOP LOSS (priority over TP)
        if trade.direction == TradeDirection.LONG:
            if current_price <= trade.stop_loss:
                return self.close_trade(symbol, trade.stop_loss, "STOP_LOSS_HIT")
            if current_price >= trade.take_profit:
                return self.close_trade(symbol, trade.take_profit, "TAKE_PROFIT_HIT")
        else:  # SHORT
            if current_price >= trade.stop_loss:
                return self.close_trade(symbol, trade.stop_loss, "STOP_LOSS_HIT")
            if current_price <= trade.take_profit:
                return self.close_trade(symbol, trade.take_profit, "TAKE_PROFIT_HIT")

        return None

    def print_status(self):
        """Print account summary."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        logger.info("=" * 80)
        logger.info(f"💰 ACCOUNT STATUS")
        logger.info(f"   Starting Balance: ${self.starting_balance:.2f}")
        logger.info(f"   Current Balance:  ${self.current_balance:.2f}")
        logger.info(f"   Total P&L:        ${self.total_pnl:+.2f}")
        logger.info(f"   Return:           {(self.total_pnl / self.starting_balance * 100):+.2f}%")
        logger.info(f"   Trades:           {self.total_trades} (W:{self.winning_trades} L:{self.losing_trades}) {win_rate:.1f}%")
        logger.info(f"   Open Positions:   {len(self.open_positions)}")
        logger.info("=" * 80)

# ============================================================================
# MARKET DATA (HTTPS PUBLIC API ONLY)
# ============================================================================

class MarketData:
    """Fetches data from Binance PUBLIC HTTPS endpoints only.
    No authentication required.
    """
    
    def __init__(self):
        self.current_prices: Dict[str, float] = {}

    async def fetch_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> List[List]:
        """Fetch candlestick data from PUBLIC Binance API.
        Endpoint: GET /api/v3/klines (no auth required)
        Returns: [[timestamp, open, high, low, close, volume, ...], ...]
        """
        try:
            url = f"{BINANCE_API_PUBLIC}/klines"
            params = {'symbol': symbol, 'interval': interval, 'limit': limit}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:  # Rate limit
                        logger.warning(f"Rate limited on {symbol} (HTTP 429), will retry next scan")
                        return []
                    else:
                        logger.error(f"Failed to fetch {symbol} klines: HTTP {resp.status}")
                        return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {symbol} klines (10s)")
            return []
        except Exception as e:
            logger.error(f"Error fetching {symbol} klines: {type(e).__name__}: {e}")
            return []

    async def fetch_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from PUBLIC Binance API.
        Endpoint: GET /api/v3/ticker/price (no auth required)
        """
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
                    elif resp.status == 429:  # Rate limit
                        logger.warning(f"Rate limited on {symbol} (HTTP 429)")
                        return None
                    else:
                        logger.error(f"Failed to fetch {symbol} price: HTTP {resp.status}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {symbol} price (10s)")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol} price: {type(e).__name__}: {e}")
            return None

# ============================================================================
# INDICATORS
# ============================================================================

def calculate_ema(prices: List[float], period: int = 9) -> float:
    """Exponential Moving Average.
    Formula: EMA = price * multiplier + EMA_prev * (1 - multiplier)
    """
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * multiplier + ema * (1 - multiplier)
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Relative Strength Index.
    Formula: RSI = 100 - (100 / (1 + RS)) where RS = avg_gain / avg_loss
    """
    if len(prices) < period:
        return 50  # Neutral
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    seed = deltas[:period]
    up = sum(x for x in seed if x > 0) / period
    down = sum(abs(x) for x in seed if x < 0) / period
    
    rs = up / down if down != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    
    # Smooth RSI over remaining deltas
    for delta in deltas[period:]:
        up = (up * (period - 1) + (delta if delta > 0 else 0)) / period
        down = (down * (period - 1) + (abs(delta) if delta < 0 else 0)) / period
        rs = up / down if down != 0 else 0
        rsi = 100 - (100 / (1 + rs))
    
    return rsi

def generate_signal(symbol: str, klines_1h: List[List], klines_4h: List[List], current_price: float) -> Signal:
    """Generate LONG/SHORT/NO_TRADE signal based on 1h and 4h timeframes.
    
    Rules:
    - LONG: Price > EMA(9) on both 1h & 4h, RSI < 70 on both
    - SHORT: Price < EMA(9) on both 1h & 4h, RSI > 30 on both
    - Otherwise: NO_TRADE
    """
    
    # Extract close prices (index 4 in kline)
    try:
        closes_1h = [float(k[4]) for k in klines_1h]
        closes_4h = [float(k[4]) for k in klines_4h]
    except (IndexError, ValueError, TypeError):
        logger.warning(f"{symbol}: Invalid kline data")
        return Signal(symbol, TradeDirection.NO_TRADE, current_price, current_price, current_price, 0.0, "Invalid data", datetime.now())
    
    if not closes_1h or not closes_4h:
        return Signal(symbol, TradeDirection.NO_TRADE, current_price, current_price, current_price, 0.0, "Insufficient data", datetime.now())
    
    # Calculate indicators
    ema_1h = calculate_ema(closes_1h, 9)
    ema_4h = calculate_ema(closes_4h, 9)
    rsi_1h = calculate_rsi(closes_1h, 14)
    rsi_4h = calculate_rsi(closes_4h, 14)
    
    direction = TradeDirection.NO_TRADE
    confidence = 0.0
    reasoning = ""
    
    # LONG: Price above both EMAs + RSI not overbought
    if current_price > ema_1h and current_price > ema_4h and rsi_1h < 70 and rsi_4h < 70:
        direction = TradeDirection.LONG
        confidence = 0.75
        reasoning = f"Price > EMA(1h:{ema_1h:.2f}/4h:{ema_4h:.2f}), RSI bullish (1h:{rsi_1h:.1f}/4h:{rsi_4h:.1f})"
    
    # SHORT: Price below both EMAs + RSI not oversold
    elif current_price < ema_1h and current_price < ema_4h and rsi_1h > 30 and rsi_4h > 30:
        direction = TradeDirection.SHORT
        confidence = 0.75
        reasoning = f"Price < EMA(1h:{ema_1h:.2f}/4h:{ema_4h:.2f}), RSI bearish (1h:{rsi_1h:.1f}/4h:{rsi_4h:.1f})"
    
    else:
        reasoning = "No setup matched"
    
    # Calculate SL/TP based on recent volatility (ATR estimate)
    if direction != TradeDirection.NO_TRADE:
        atr_estimate = max(closes_1h[-20:]) - min(closes_1h[-20:])
        if atr_estimate == 0:
            atr_estimate = current_price * 0.02  # Default 2% if no volatility
        
        if direction == TradeDirection.LONG:
            entry = current_price
            stop_loss = current_price - atr_estimate * 0.5
            take_profit = current_price + atr_estimate * 2.5  # ~1:5 risk/reward
        else:  # SHORT
            entry = current_price
            stop_loss = current_price + atr_estimate * 0.5
            take_profit = current_price - atr_estimate * 2.5
    else:
        entry = stop_loss = take_profit = current_price
    
    return Signal(symbol, direction, entry, stop_loss, take_profit, confidence, reasoning, datetime.now())

# ============================================================================
# MAIN BOT LOOP
# ============================================================================

async def main():
    """Main async event loop. Runs indefinitely on Railway.
    
    Concurrency model:
    - All Binance API calls run concurrently via asyncio.gather()
    - Account state is single-threaded (no race conditions)
    - Gracefully handles timeouts and API errors
    """
    
    logger.info("=" * 80)
    logger.info("🤖 CRYPTO PAPER-TRADING BOT STARTED")
    logger.info(f"   Safety Mode: PAPER TRADING ONLY (PAPER_MODE=true)")
    logger.info(f"   Starting Balance: ${STARTING_BALANCE:.2f}")
    logger.info(f"   Risk per Trade: {RISK_PER_TRADE * 100:.2f}% of current equity")
    logger.info(f"   Confidence Threshold: {CONFIDENCE_THRESHOLD * 100:.1f}%")
    logger.info(f"   Symbols: {', '.join(SYMBOLS)}")
    logger.info(f"   Scan Interval: {SCAN_INTERVAL}s")
    logger.info("=" * 80)

    account = SimulatedAccount(STARTING_BALANCE)
    market = MarketData()
    scan_count = 0

    while True:
        try:
            scan_count += 1
            logger.info(f"\n📡 SCAN #{scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # CONCURRENT API CALLS (asyncio.gather)
            tasks = []
            for symbol in SYMBOLS:
                tasks.append(market.fetch_current_price(symbol))
                tasks.append(market.fetch_klines(symbol, '1h', 100))
                tasks.append(market.fetch_klines(symbol, '4h', 100))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # PROCESS RESULTS (sequential to prevent race conditions)
            idx = 0
            for symbol in SYMBOLS:
                current_price = results[idx]
                klines_1h = results[idx + 1]
                klines_4h = results[idx + 2]
                idx += 3

                # Handle fetch errors
                if isinstance(current_price, Exception) or current_price is None:
                    logger.warning(f"Skipping {symbol}: price fetch failed")
                    continue

                # Check open positions for SL/TP (before generating new signals)
                account.check_sl_tp(symbol, current_price)

                # Generate signal if we have data
                if isinstance(klines_1h, list) and isinstance(klines_4h, list) and len(klines_1h) > 0 and len(klines_4h) > 0:
                    signal = generate_signal(symbol, klines_1h, klines_4h, current_price)

                    # Enter trade only if confidence meets threshold
                    if signal.direction != TradeDirection.NO_TRADE and signal.confidence >= CONFIDENCE_THRESHOLD:
                        account.open_trade(signal)
                    elif signal.direction != TradeDirection.NO_TRADE:
                        logger.debug(
                            f"Signal rejected {symbol} {signal.direction.value}: "
                            f"confidence {signal.confidence:.2f} < {CONFIDENCE_THRESHOLD:.2f}"
                        )

            # Print status every 3 scans
            if scan_count % 3 == 0:
                account.print_status()

            logger.info(f"⏳ Waiting {SCAN_INTERVAL}s until next scan...")
            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            logger.error(f"Error in main loop: {type(e).__name__}: {e}", exc_info=False)
            await asyncio.sleep(10)  # Brief pause before retry

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {type(e).__name__}: {e}", exc_info=True)
        sys.exit(1)
