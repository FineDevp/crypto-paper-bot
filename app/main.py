from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
import os, time, threading, logging
from collections import deque

# Database
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL','300'))
START_BALANCE = float(os.getenv('START_BALANCE','50.0'))
DASH_TOKEN = os.getenv('DASHBOARD_TOKEN','')
DATABASE_URL = os.getenv('DATABASE_URL','sqlite:///./data.db')

app = FastAPI()

# mount static built dashboard
if os.path.isdir('dashboard/dist'):
    app.mount('/', StaticFiles(directory='dashboard/dist', html=True), name='static')

state = {
    'running': True,
    'last_scan': None,
    'open_trades': [],
    'balance': START_BALANCE
}
logs = deque(maxlen=500)

# initialize DB engine
_engine: Engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    url = DATABASE_URL
    logging.info(f"Using DATABASE_URL={url}")
    # if using sqlite, enable check_same_thread
    if url.startswith('sqlite'):
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        _engine = create_engine(url)
    init_db(_engine)
    return _engine


def init_db(engine: Engine):
    # create trades table if not exists
    create_sql = '''
    CREATE TABLE IF NOT EXISTS trades (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        symbol TEXT,
        size REAL,
        risk REAL,
        action TEXT,
        price REAL,
        paper BOOLEAN
    );
    '''
    # For sqlite, SERIAL isn't supported — adapt
    if DATABASE_URL.startswith('sqlite'):
        create_sql = '''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            size REAL,
            risk REAL,
            action TEXT,
            price REAL,
            paper BOOLEAN
        );
        '''
    with engine.connect() as conn:
        conn.execute(text(create_sql))
        conn.commit()


def log(msg: str):
    logging.info(msg)
    logs.appendleft(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}")


def insert_trade_record(trade: dict):
    engine = get_engine()
    sql = text('''INSERT INTO trades(symbol,size,risk,action,price,paper) VALUES(:symbol,:size,:risk,:action,:price,:paper)''')
    with engine.connect() as conn:
        conn.execute(sql, **{
            'symbol': trade.get('symbol'),
            'size': float(trade.get('size', 0)),
            'risk': float(trade.get('risk', 0)),
            'action': trade.get('action', 'open'),
            'price': float(trade.get('price') or 0),
            'paper': bool(trade.get('paper', True))
        })
        conn.commit()


def get_trade_history(limit: int = 100):
    engine = get_engine()
    sql = text('SELECT id, ts, symbol, size, risk, action, price, paper FROM trades ORDER BY id DESC LIMIT :lim')
    with engine.connect() as conn:
        rows = conn.execute(sql, {'lim': limit}).fetchall()
    results = []
    for r in rows:
        results.append({
            'id': r[0],
            'ts': str(r[1]),
            'symbol': r[2],
            'size': r[3],
            'risk': r[4],
            'action': r[5],
            'price': r[6],
            'paper': bool(r[7])
        })
    return results


def do_scan_once():
    # placeholder for real scan/trade logic
    log('scan: starting')
    # example: add a fake trade sometimes
    if time.time() % 2 < 1:
        t = {'symbol':'ETHUSDT','size':0.001,'risk':0.10,'action':'open','price':2661.81,'paper': os.getenv('PAPER_MODE','1')=='1'}
        state['open_trades'].append(t)
        insert_trade_record(t)
        log(f"trade opened: {t['symbol']} size={t['size']}")
    state['last_scan'] = int(time.time())
    # fake balance fluctuation
    state['balance'] += (0.01 - 0.005)
    log('scan: finished')


def worker_loop():
    while True:
        try:
            if state['running']:
                do_scan_once()
            else:
                log('worker paused')
        except Exception as e:
            logging.exception('scan failed')
            logs.appendleft(f"ERROR: {e}")
        for _ in range(max(1, SCAN_INTERVAL // 10)):
            time.sleep(10)
            # heartbeat log at debug level
            logging.debug('heartbeat')

threading.Thread(target=worker_loop, daemon=True).start()


def require_token(req: Request):
    if not DASH_TOKEN:
        return
    header = req.headers.get('x-dashboard-token')
    if header != DASH_TOKEN:
        raise HTTPException(status_code=401, detail='unauthorized')

@app.get('/api/health')
async def health():
    return {'status':'ok','running':state['running']}

@app.get('/api/status')
async def status():
    return {
        'running': state['running'],
        'last_scan': state['last_scan'],
        'open_trades': state['open_trades'],
        'balance': state['balance'],
        'paper_mode': os.getenv('PAPER_MODE','1'),
        'scan_interval': SCAN_INTERVAL
    }

@app.post('/api/control')
async def control(request: Request):
    require_token(request)
    body = await request.json()
    action = body.get('action')
    if action == 'pause':
        state['running'] = False
        log('control: paused')
    elif action == 'resume':
        state['running'] = True
        log('control: resumed')
    elif action == 'force_scan':
        log('control: force_scan')
        do_scan_once()
    elif action == 'toggle_paper':
        cur = os.getenv('PAPER_MODE','1')
        os.environ['PAPER_MODE'] = '0' if cur=='1' else '1'
        log(f"control: toggle_paper -> {os.environ['PAPER_MODE']}")
    else:
        return JSONResponse({'result':'unknown action'}, status_code=400)
    return {'result':'ok','action':action}

@app.get('/api/logs')
async def get_logs(limit: int = 50):
    return list(list(logs)[:limit])

@app.get('/api/trades')
async def trades(limit: int = 100):
    return get_trade_history(limit)

@app.get('/api/events')
async def events(request: Request):
    def gen():
        while True:
            # Note: EventSourceResponse will stop if client disconnects
            payload = {'type':'status','payload':{
                'running': state['running'],
                'last_scan': state['last_scan'],
                'open_trades': state['open_trades'],
                'balance': state['balance'],
                'paper_mode': os.getenv('PAPER_MODE','1'),
                'scan_interval': SCAN_INTERVAL
            }}
            yield f"data: {to_json(payload)}\n\n"
            # send last log line as well
            if logs:
                yield f"data: {to_json({'type':'log','payload':logs[0]})}\n\n"
            time.sleep(5)
    return EventSourceResponse(gen())

# small helpers
import json

def to_json(obj):
    return json.dumps(obj, default=str)
