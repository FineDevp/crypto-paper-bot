"""persistence/storage.py
SQLite persistence helpers for trades and runs.

Default DB path: ./data/paper_runs.db
"""
import sqlite3
import json
import os
from typing import Dict, Any

DB_DEFAULT = os.getenv('PAPER_DB_PATH', './data/paper_runs.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT,
    end_time TEXT,
    config_snapshot TEXT,
    starting_balance REAL,
    ending_balance REAL,
    total_pnl REAL,
    max_drawdown REAL,
    num_trades INTEGER
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    timestamp TEXT,
    symbol TEXT,
    side TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity REAL,
    stop_loss REAL,
    take_profit REAL,
    risk_amount REAL,
    rr REAL,
    signal_score REAL,
    market_regime TEXT,
    gross_pnl REAL,
    fees REAL,
    slippage REAL,
    impact REAL,
    net_pnl REAL,
    r_multiple REAL,
    exit_reason TEXT,
    metadata TEXT
);
"""


def init_db(db_path: str = DB_DEFAULT):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    conn.commit()
    conn.close()


def save_run(run: Dict[str, Any], db_path: str = DB_DEFAULT) -> int:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO runs (start_time, end_time, config_snapshot, starting_balance, ending_balance, total_pnl, max_drawdown, num_trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.get('start_time'), run.get('end_time'), json.dumps(run.get('config_snapshot', {})),
            run.get('starting_balance'), run.get('ending_balance'), run.get('total_pnl'), run.get('max_drawdown'), run.get('num_trades')
        )
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def save_trade(trade: Dict[str, Any], db_path: str = DB_DEFAULT) -> int:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trades (run_id, timestamp, symbol, side, entry_price, exit_price, quantity, stop_loss, take_profit,
            risk_amount, rr, signal_score, market_regime, gross_pnl, fees, slippage, impact, net_pnl, r_multiple, exit_reason, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.get('run_id'), trade.get('timestamp'), trade.get('symbol'), trade.get('side'), trade.get('entry_price'), trade.get('exit_price'),
            trade.get('quantity'), trade.get('stop_loss'), trade.get('take_profit'), trade.get('risk_amount'), trade.get('rr'), trade.get('signal_score'),
            trade.get('market_regime'), trade.get('gross_pnl'), trade.get('fees'), trade.get('slippage'), trade.get('impact'), trade.get('net_pnl'),
            trade.get('r_multiple'), trade.get('exit_reason'), json.dumps(trade.get('metadata', {}))
        )
    )
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def query_trades(db_path: str = DB_DEFAULT):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows
