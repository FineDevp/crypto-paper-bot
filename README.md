# Crypto Paper-Trading Bot

A **minimal, secure, modular cryptocurrency PAPER-TRADING bot** for Binance public market-data analysis.

**⚠️ PAPER TRADING ONLY** — No real orders executed. No authentication required for initial use.

## Features

✅ **Binance Public Market Data** — Fetches candlestick data (1h, 4h) via HTTPS  
✅ **Dynamic Position Sizing** — Calculates position size from 0.2% account risk  
✅ **Configurable Starting Balance** — Support $10, $25, $50, $100+  
✅ **Simple Technical Indicators** — EMA(9), RSI(14), ATR-based SL/TP  
✅ **Stop-Loss & Take-Profit Simulation** — Real-time P&L tracking  
✅ **Confidence Threshold** — Only takes trades >= 70% confidence  
✅ **Async/Concurrent Market Scanning** — Efficient data fetching  
✅ **Modular Code** — Easy to extend with new strategies  
✅ **Comprehensive Logging** — Status updates and trade results  
✅ **Environment-Based Configuration** — No hardcoded values  
✅ **Railway.app Ready** — Runs on Railway with minimal setup  

## Safety & Security

- **PAPER_MODE=true** is mandatory. Real trading is NOT implemented.
- No Binance order endpoints used.
- No API credentials required for public market data.
- `.gitignore` excludes `.env`, databases, and logs.
- Position size validated against account equity.
- Duplicate positions prevented.

## Quick Start

### Local Installation

```bash
# Clone the repository
git clone https://github.com/FineDevp/crypto-paper-bot.git
cd crypto-paper-bot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Local Execution

```bash
# Run with defaults ($50 starting balance, BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT)
python bot.py

# Or customize:
export STARTING_BALANCE=100
export RISK_PER_TRADE=0.002  # 0.2%
export TARGET_RETURN=0.01    # 1%
export SCAN_INTERVAL_SECONDS=300
export CONFIDENCE_THRESHOLD=0.7
export SYMBOLS="BTCUSDT,ETHUSDT"
python bot.py
```

### Environment Variables

Create a `.env` file (or set in your environment):

```
PAPER_MODE=true
STARTING_BALANCE=50
RISK_PER_TRADE=0.002
TARGET_RETURN=0.01
SCAN_INTERVAL_SECONDS=300
CONFIDENCE_THRESHOLD=0.7
SLIPPAGE=0.001
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT
```

- `PAPER_MODE` — Must be `true` (safety lock)
- `STARTING_BALANCE` — Initial account equity in USD (default: 50)
- `RISK_PER_TRADE` — Risk per trade as % of balance (default: 0.002 = 0.2%)
- `TARGET_RETURN` — Target profit per trade as % (default: 0.01 = 1%)
- `SCAN_INTERVAL_SECONDS` — Time between market scans (default: 300)
- `CONFIDENCE_THRESHOLD` — Min confidence to enter trade (default: 0.7 = 70%)
- `SLIPPAGE` — Estimated slippage/fees as % (default: 0.001 = 0.1%)
- `SYMBOLS` — Comma-separated trading pairs (default: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT)

## Architecture

### `bot.py`
- Main async event loop
- Market data fetching (concurrent tasks)
- Signal generation and trade management
- Account state tracking
- Stop-loss / take-profit simulation
- Logging and status reporting

### Key Classes

**SimulatedAccount**
- Tracks balance, equity, and open positions
- Calculates risk-based position size
- Opens/closes simulated trades
- Computes realized & unrealized P&L
- Prevents duplicate positions

**MarketData**
- Fetches current prices from Binance
- Fetches candlestick data (klines)
- Handles API errors and timeouts gracefully

**Signal**
- Symbol, direction (LONG/SHORT/NO_TRADE)
- Entry, stop-loss, take-profit levels
- Confidence score
- Reasoning

**Trade**
- Stores all trade details
- Tracks entry/exit prices, P&L, status
- Used for post-trade analysis

### Strategy Logic

**Indicators:**
- **EMA(9)** — Exponential Moving Average (trend direction)
- **RSI(14)** — Relative Strength Index (overbought/oversold)
- **ATR Estimate** — Range-based stop-loss and take-profit sizing

**Rules:**
- **LONG**: Price > EMA(1h) AND Price > EMA(4h) AND RSI(1h) < 70 AND RSI(4h) < 70
- **SHORT**: Price < EMA(1h) AND Price < EMA(4h) AND RSI(1h) > 30 AND RSI(4h) > 30
- **NO_TRADE**: Otherwise
- Confidence: 0.75 (75%) when conditions met
- Entry only if confidence ≥ threshold

**Position Sizing:**
```
Risk Amount = Current Balance × 0.2%
Position Size = Risk Amount / (Entry - StopLoss)
```

**Take-Profit / Stop-Loss:**
- Stop-Loss: ATR × 0.5
- Take-Profit: ATR × 2.5 (approximately 1:5 risk/reward)

## Simulation Example

**Starting:** $50  
**Risk per trade:** 0.2% = $0.10  
**First trade (LONG BTC):**
- Entry: $42,000
- Stop Loss: $41,900 (distance: $100)
- Take Profit: $42,250
- Position Size: 0.10 / 100 = 0.001 BTC
- Max Loss: $0.10 (0.2% of $50)
- Max Gain: $0.25 (0.5% of $50)

**If trade wins:** Balance → $50.25  
**If trade loses:** Balance → $49.90

## Adding Custom Strategies

The `generate_signal()` function can be extended:

```python
def generate_signal(symbol: str, klines_1h, klines_4h, current_price):
    # Your custom logic here
    # Return a Signal object
    return Signal(...)
```

Future versions will support:
- Strategy factory pattern
- Multiple simultaneous strategies per symbol
- Custom indicator modules
- Backtesting framework

## Railway Deployment

1. **Fork/Clone this repo to your GitHub account**

2. **Connect to Railway:**
   - Go to [Railway.app](https://railway.app)
   - Create new project → Deploy from GitHub repo
   - Select `crypto-paper-bot`

3. **Configure environment:**
   - Set `PAPER_MODE=true`
   - Set `STARTING_BALANCE`, `SYMBOLS`, etc. in Railway variables
   - No API keys needed for public data

4. **Deploy:**
   - Push to `main` branch or trigger manual deploy
   - Bot runs continuously in Railway

## Logs & Monitoring

The bot logs to stdout with timestamps:

```
2026-08-24 10:15:00 - bot - INFO - 🤖 CRYPTO PAPER-TRADING BOT STARTED
2026-08-24 10:15:05 - bot - INFO - 📡 SCAN #1
2026-08-24 10:15:15 - bot - INFO - 📈 TRADE OPENED: BTCUSDT LONG | ...
2026-08-24 10:15:25 - bot - INFO - 💰 ACCOUNT STATUS
```

On Railway, view logs in the deployment dashboard.

## Risk Disclaimers

⚠️ **PAPER TRADING SIMULATION ONLY**
- This bot does NOT execute real trades.
- Past performance ≠ future results.
- Market conditions vary; strategy may underperform.
- Use for learning and backtesting only.

⚠️ **NO LIABILITY**
- This software is provided as-is.
- The author assumes no responsibility for losses.
- Test thoroughly before any real trading.

## Future Enhancements

- [ ] Backtesting framework
- [ ] Multiple strategies per symbol
- [ ] Advanced indicators (Bollinger Bands, MACD, etc.)
- [ ] Database persistence (SQLite/PostgreSQL)
- [ ] Web dashboard for monitoring
- [ ] Real Binance integration (with full safety checks)
- [ ] Strategy performance analytics
- [ ] Alert notifications (Discord, Telegram)

## License

MIT License — See LICENSE file for details.

## Author

**FineDevp** — Cryptocurrency & Algorithmic Trading  
Questions? Open an issue on GitHub.

---

**Remember:** This is a paper-trading bot for learning and analysis. Never use real money without extensive backtesting and risk management expertise.
