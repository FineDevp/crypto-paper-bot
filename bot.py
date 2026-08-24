#!/usr/bin/env python3
"""
Minimal Paper-Trading Bot for Binance Public Market Data
PAPER TRADING ONLY - No real orders executed
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import aiohttp
import asyncio

# ============================================================================
# CONFIGURATION & LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Mandatory safety check
PAPER_MODE = os.getenv('PAPER_MODE', 'true').lower() == 'true'
if not PAPER_MODE:
    logger.error("PAPER_MODE must be true. Real trading is NOT implemented.")
    sys.exit(1)

# Configuration from environment
STARTING_BALANCE = float(os.getenv('STARTING_BALANCE', '50'))
RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '0.002'))  # 0.2%
TARGET_RETURN = float(os.getenv('TARGET_RETURN', '0.01'))  # 1%
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL_SECONDS', '300'))  # 5 minutes
CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '0.7'))  # 70%
SLIPPAGE = float(os.getenv('SLIPPAGE', '0.001'))  # 0.1%

SYMBOLS = os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')
TIMEFRAMES = ['1h', '4h']  # 1 hour and 4 hour candles

BINANCE_API = "https://api.binance.com/api/v3"

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
    status: str = "OPEN"  # OPEN, WIN, LOSS, CANCELLED

# ============================================================================
# ACCOUNT STATE
# ============================================================================

class SimulatedAccount:
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.trades: List[Trade] = []
        self.open_positions: Dict[str, Trade] = {}  # symbol -> Trade
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

    def get_available_risk(self) -> float:
        """Risk amount in USD for next trade (0.2% of current balance)"""
        return self.current_balance * RISK_PER_TRADE

    def calculate_position_size(self, risk_amount: float, entry: float, stop_loss: float) -> float:
        """Calculate position size in base currency units"""
        distance_to_sl = abs(entry - stop_loss)
        if distance_to_sl == 0:
            return 0
        position_size = risk_amount / distance_to_sl
        return position_size

    def open_trade(self, signal: Signal) -> Optional[Trade]:
        """Open a new paper trade"""
        # Prevent duplicate positions
        if signal.symbol in self.open_positions:
            logger.warning(f"Position already open for {signal.symbol}, skipping")
            return None

        risk_amount = self.get_available_risk()
        if risk_amount <= 0:
            logger.warning(f"Insufficient balance for {signal.symbol}")
            return None

        position_size = self.calculate_position_size(risk_amount, signal.entry, signal.stop_loss)
        
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

        self.open_positions[signal.symbol] = trade
        self.trades.append(trade)
        self.total_trades += 1

        logger.info(
            f"📈 TRADE OPENED: {signal.symbol} {signal.direction.value} | "
            f"Entry: ${signal.entry:.2f} | SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f} | "
            f"Size: {position_size:.4f} | Risk: ${risk_amount:.2f}"
        )
        return trade

    def close_trade(self, symbol: str, exit_price: float, reason: str = "MANUAL") -> Optional[Trade]:
        """Close a paper trade and calculate P&L"""
        if symbol not in self.open_positions:
            return None

        trade = self.open_positions[symbol]
        trade.exit_price = exit_price
        trade.exit_time = datetime.now()

        # Calculate P&L
        if trade.direction == TradeDirection.LONG:
            price_change = exit_price - trade.entry
        else:  # SHORT
            price_change = trade.entry - exit_price

        pnl = price_change * trade.position_size - (trade.position_size * exit_price * SLIPPAGE * 2)
        trade.pnl = pnl
        trade.status = "WIN" if pnl > 0 else "LOSS"

        # Update account
        self.current_balance += pnl
        self.total_pnl += pnl

        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        del self.open_positions[symbol]

        logger.info(
            f"🏁 TRADE CLOSED: {symbol} {trade.direction.value} | "
            f"Exit: ${exit_price:.2f} | P&L: ${pnl:+.2f} | "
            f"Balance: ${self.current_balance:.2f} | {reason}"
        )
        return trade

    def check_sl_tp(self, symbol: str, current_price: float) -> Optional[Trade]:
        """Check if any open trade hit stop-loss or take-profit"""
        if symbol not in self.open_positions:
            return None

        trade = self.open_positions[symbol]

        # Check stop loss
        if trade.direction == TradeDirection.LONG and current_price <= trade.stop_loss:
            return self.close_trade(symbol, trade.stop_loss, "STOP_LOSS_HIT")

        if trade.direction == TradeDirection.SHORT and current_price >= trade.stop_loss:
            return self.close_trade(symbol, trade.stop_loss, "STOP_LOSS_HIT")

        # Check take profit
        if trade.direction == TradeDirection.LONG and current_price >= trade.take_profit:
            return self.close_trade(symbol, trade.take_profit, "TAKE_PROFIT_HIT")

        if trade.direction == TradeDirection.SHORT and current_price <= trade.take_profit:
            return self.close_trade(symbol, trade.take_profit, "TAKE_PROFIT_HIT")

        return None

    def print_status(self):
        """Print account status"""
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
# MARKET DATA & INDICATORS
# ============================================================================

class MarketData:
    def __init__(self):
        self.klines_cache: Dict[str, Dict[str, List]] = {}
        self.current_prices: Dict[str, float] = {}

    async def fetch_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> List[Dict]:
        """Fetch candlestick data from Binance public API"""
        try:
            url = f"{BINANCE_API}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data
                    else:
                        logger.error(f"Failed to fetch {symbol}: HTTP {resp.status}")
                        return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {symbol}")
            return []
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return []

    async def fetch_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Binance"""
        try:
            url = f"{BINANCE_API}/ticker/price"
            params = {'symbol': symbol}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data['price'])
                        self.current_prices[symbol] = price
                        return price
                    else:
                        logger.error(f"Failed to fetch price for {symbol}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None

# ============================================================================
# SIMPLE STRATEGY
# ============================================================================

def calculate_ema(prices: List[float], period: int = 9) -> float:
    """Simple EMA calculation"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * multiplier + ema * (1 - multiplier)
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Simple RSI calculation"""
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

def generate_signal(symbol: str, klines_1h: List[Dict], klines_4h: List[Dict], current_price: float) -> Signal:
    """
    Generate a LONG/SHORT/NO_TRADE signal based on simple rules.
    
    Rules:
    - LONG: Price > EMA(9), RSI(14) < 70, confidence >= threshold
    - SHORT: Price < EMA(9), RSI(14) > 30, confidence >= threshold
    - Otherwise: NO_TRADE
    """
    
    # Extract close prices
    closes_1h = [float(k[4]) for k in klines_1h]
    closes_4h = [float(k[4]) for k in klines_4h]
    
    if not closes_1h or not closes_4h:
        return Signal(
            symbol=symbol,
            direction=TradeDirection.NO_TRADE,
            entry=current_price,
            stop_loss=current_price,
            take_profit=current_price,
            confidence=0.0,
            reasoning="Insufficient data",
            timestamp=datetime.now()
        )
    
    # Calculate indicators
    ema_1h = calculate_ema(closes_1h, 9)
    ema_4h = calculate_ema(closes_4h, 9)
    rsi_1h = calculate_rsi(closes_1h, 14)
    rsi_4h = calculate_rsi(closes_4h, 14)
    
    direction = TradeDirection.NO_TRADE
    confidence = 0.0
    reasoning = ""
    
    # LONG conditions
    if current_price > ema_1h and current_price > ema_4h and rsi_1h < 70 and rsi_4h < 70:
        direction = TradeDirection.LONG
        confidence = 0.75
        reasoning = f"Price > EMA(1h/4h), RSI bullish (1h:{rsi_1h:.1f}, 4h:{rsi_4h:.1f})"
    
    # SHORT conditions
    elif current_price < ema_1h and current_price < ema_4h and rsi_1h > 30 and rsi_4h > 30:
        direction = TradeDirection.SHORT
        confidence = 0.75
        reasoning = f"Price < EMA(1h/4h), RSI bearish (1h:{rsi_1h:.1f}, 4h:{rsi_4h:.1f})"
    
    else:
        reasoning = "No setup matched criteria"
    
    # Calculate entry, SL, TP
    if direction == TradeDirection.LONG:
        atr_estimate = max(closes_1h[-20:]) - min(closes_1h[-20:])
        entry = current_price
        stop_loss = current_price - atr_estimate * 0.5
        take_profit = current_price + (atr_estimate * 2.5)  # 1:5 risk/reward target
    
    elif direction == TradeDirection.SHORT:
        atr_estimate = max(closes_1h[-20:]) - min(closes_1h[-20:])
        entry = current_price
        stop_loss = current_price + atr_estimate * 0.5
        take_profit = current_price - (atr_estimate * 2.5)
    
    else:
        entry = current_price
        stop_loss = current_price
        take_profit = current_price
    
    return Signal(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=confidence,
        reasoning=reasoning,
        timestamp=datetime.now()
    )

# ============================================================================
# MAIN BOT LOOP
# ============================================================================

async def main():
    logger.info("=" * 80)
    logger.info("🤖 CRYPTO PAPER-TRADING BOT STARTED")
    logger.info(f"   Mode: PAPER TRADING ONLY")
    logger.info(f"   Starting Balance: ${STARTING_BALANCE}")
    logger.info(f"   Risk per Trade: {RISK_PER_TRADE * 100:.2f}%")
    logger.info(f"   Target Return: {TARGET_RETURN * 100:.2f}%")
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

            # Fetch market data for all symbols
            tasks = []
            for symbol in SYMBOLS:
                tasks.append(market.fetch_current_price(symbol))
                tasks.append(market.fetch_klines(symbol, '1h', 100))
                tasks.append(market.fetch_klines(symbol, '4h', 100))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            idx = 0
            for symbol in SYMBOLS:
                current_price = results[idx]
                klines_1h = results[idx + 1]
                klines_4h = results[idx + 2]
                idx += 3

                # Handle errors
                if isinstance(current_price, Exception) or current_price is None:
                    logger.warning(f"Failed to fetch data for {symbol}")
                    continue

                # Check open positions for SL/TP
                account.check_sl_tp(symbol, current_price)

                # Generate signal
                if isinstance(klines_1h, list) and isinstance(klines_4h, list):
                    signal = generate_signal(symbol, klines_1h, klines_4h, current_price)

                    # Only open trade if confidence meets threshold
                    if signal.direction != TradeDirection.NO_TRADE and signal.confidence >= CONFIDENCE_THRESHOLD:
                        account.open_trade(signal)
                    elif signal.direction != TradeDirection.NO_TRADE:
                        logger.info(
                            f"⏭️  SIGNAL REJECTED {symbol} {signal.direction.value}: "
                            f"Confidence {signal.confidence:.2f} < {CONFIDENCE_THRESHOLD:.2f}"
                        )

            # Print account status every 3 scans
            if scan_count % 3 == 0:
                account.print_status()

            # Wait before next scan
            logger.info(f"⏳ Waiting {SCAN_INTERVAL}s until next scan...")
            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            await asyncio.sleep(10)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
        sys.exit(0)
