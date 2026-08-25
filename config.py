"""config.py
Centralized environment configuration for crypto-paper-bot.
This file defines all environment/configuration variables requested by the mentor upgrade.

Do NOT disable PAPER_MODE in this file — the bot must always run in paper mode by default.
"""

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class MarketImpactConfig:
    liquidity: float = float(os.getenv('IMPACT_LIQUIDITY', '100.0'))
    alpha: float = float(os.getenv('IMPACT_ALPHA', '0.5'))
    k: float = float(os.getenv('IMPACT_K', '1.0'))
    tick_size: float = float(os.getenv('TICK_SIZE', '0.01'))
    max_ticks: int = int(os.getenv('IMPACT_MAX_TICKS', '100'))
    decay_tau_sec: float = float(os.getenv('IMPACT_DECAY_TAU_SEC', '60'))

@dataclass
class FeesConfig:
    maker: float = float(os.getenv('FEE_MAKER', '0.001'))
    taker: float = float(os.getenv('FEE_TAKER', '0.001'))

@dataclass
class Config:
    # Safety lock
    PAPER_MODE: bool = os.getenv('PAPER_MODE', 'true').lower() == 'true'

    # Account & sizing
    STARTING_BALANCE: float = float(os.getenv('STARTING_BALANCE', '100'))
    RISK_PER_TRADE: float = float(os.getenv('RISK_PER_TRADE', '0.005'))  # 0.5% default
    RISK_REWARD: float = float(os.getenv('RISK_REWARD', '2.5'))
    MAX_SIMULTANEOUS_POSITIONS: int = int(os.getenv('MAX_SIMULTANEOUS_POSITIONS', '3'))

    # Hard risk limits
    MAX_DAILY_LOSS: float = float(os.getenv('MAX_DAILY_LOSS', '10.0'))  # percent of starting balance
    MAX_DRAWDOWN: float = float(os.getenv('MAX_DRAWDOWN', '25.0'))  # percent
    MAX_CONSECUTIVE_LOSSES: int = int(os.getenv('MAX_CONSECUTIVE_LOSSES', '5'))
    COOLDOWN_AFTER_CONSECUTIVE_LOSSES: int = int(os.getenv('COOLDOWN_AFTER_CONSECUTIVE_LOSSES', '60'))  # seconds
    MAX_TRADES_PER_DAY: int = int(os.getenv('MAX_TRADES_PER_DAY', '50'))

    # Execution & simulation
    SLIPPAGE: float = float(os.getenv('SLIPPAGE', '0.001'))
    FEES: FeesConfig = FeesConfig()
    MARKET_IMPACT: MarketImpactConfig = MarketImpactConfig()
    SIMULATE_PARTIAL_FILLS: bool = os.getenv('SIMULATE_PARTIAL_FILLS', 'true').lower() == 'true'

    # Market data / behaviour
    SYMBOLS: list = [s.strip() for s in os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT').split(',')]
    TIMEFRAMES: list = [tf.strip() for tf in os.getenv('TIMEFRAMES', '15m,1h,4h').split(',')]
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS', '300'))

    # Backtest
    BACKTEST_MODE: bool = os.getenv('BACKTEST_MODE', 'false').lower() == 'true'

    # Safety toggles (must remain conservative)
    ALLOW_REAL_ORDERS: bool = os.getenv('ALLOW_REAL_ORDERS', 'false').lower() == 'true'


# Single global config instance for imports
cfg = Config()

# Enforce PAPER_MODE at import-time as a defensive safety measure
if not cfg.PAPER_MODE:
    raise RuntimeError("PAPER_MODE must be true. This repository only supports paper-trading by default.")
