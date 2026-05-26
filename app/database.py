import psycopg2, psycopg2.pool
from app.config import DATABASE_URL
from datetime import date

_pool = None
def _get_pool():
    global _pool
    if _pool is None: _pool = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL)
    return _pool
def get_conn(): return _get_pool().getconn()
def release_conn(conn): _get_pool().putconn(conn)
def _row(cur, row): return dict(zip([d[0] for d in cur.description], row)) if row else None

def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS portfolio (
                id SERIAL PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT NOW(),
                initial_capital_eur NUMERIC(20,8), initial_capital_usdt NUMERIC(20,8),
                btc_eur_rate_at_start NUMERIC(20,8), current_capital_usdt NUMERIC(20,8),
                currency VARCHAR(10) DEFAULT 'EUR', is_active BOOLEAN DEFAULT TRUE)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY, portfolio_id INTEGER REFERENCES portfolio(id),
                symbol VARCHAR(20) DEFAULT 'BTCUSDT', timeframe VARCHAR(5), action VARCHAR(10),
                status VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED_TP','CLOSED_SL','CLOSED_MANUAL','ERROR')),
                entry_price NUMERIC(20,8), exit_price NUMERIC(20,8),
                stop_loss NUMERIC(20,8), take_profit NUMERIC(20,8),
                quantity NUMERIC(20,8), risk_amount_usdt NUMERIC(20,8),
                pnl_usdt NUMERIC(20,8), pnl_eur NUMERIC(20,8), pnl_pct NUMERIC(10,4),
                fees_usdt NUMERIC(20,8), signal_rsi NUMERIC(10,4),
                signal_ema20 NUMERIC(20,8), signal_ema50 NUMERIC(20,8),
                signal_atr NUMERIC(20,8),
                ai_decision VARCHAR(10) DEFAULT 'PENDING',
                ai_confidence INTEGER, ai_reasoning TEXT,
                opened_at TIMESTAMPTZ DEFAULT NOW(),
                closed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW())''')
            cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS symbol VARCHAR(20) DEFAULT 'BTCUSDT'")
            cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_atr NUMERIC(20,8)")
            cur.execute('''CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY, symbol VARCHAR(20), timeframe VARCHAR(5), action VARCHAR(10),
                price NUMERIC(20,8), rsi NUMERIC(10,4), ema20 NUMERIC(20,8), ema50 NUMERIC(20,8),
                was_executed BOOLEAN DEFAULT FALSE, rejection_reason TEXT,
                detected_at TIMESTAMPTZ DEFAULT NOW())''')
            cur.execute('''CREATE TABLE IF NOT EXISTS risk_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                kill_switch_active BOOLEAN DEFAULT FALSE, kill_switch_reason TEXT,
                has_open_position BOOLEAN DEFAULT FALSE, current_trade_id INTEGER,
                trades_today INTEGER DEFAULT 0, consecutive_losses INTEGER DEFAULT 0,
                daily_pnl_usdt NUMERIC(20,8) DEFAULT 0, trading_date DATE DEFAULT CURRENT_DATE,
                last_updated TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT single_row CHECK (id = 1))''')
            cur.execute('''CREATE TABLE IF NOT EXISTS daily_summaries (
                id SERIAL PRIMARY KEY, summary_date DATE UNIQUE,
                total_signals INTEGER DEFAULT 0, executed_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0, losing_trades INTEGER DEFAULT 0,
                pnl_usdt NUMERIC(20,8) DEFAULT 0, pnl_eur NUMERIC(20,8) DEFAULT 0,
                win_rate NUMERIC(5,2) DEFAULT 0, closing_capital_usdt NUMERIC(20,8),
                created_at TIMESTAMPTZ DEFAULT NOW())''')
            cur.execute('''CREATE TABLE IF NOT EXISTS system_logs (
                id SERIAL PRIMARY KEY,
                level VARCHAR(10) CHECK (level IN ('INFO','WARN','ERROR')),
                component VARCHAR(50), message TEXT, trade_id INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW())''')
            conn.commit()
    finally: release_conn(conn)

def get_active_portfolio():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM portfolio WHERE is_active=TRUE ORDER BY id DESC LIMIT 1")
            return _row(cur, cur.fetchone())
    finally: release_conn(conn)

def create_portfolio(initial_capital_eur, initial_capital_usdt, btc_rate):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO portfolio (initial_capital_eur,initial_capital_usdt,btc_eur_rate_at_start,current_capital_usdt) VALUES (%s,%s,%s,%s) RETURNING *",
                (initial_capital_eur,initial_capital_usdt,btc_rate,initial_capital_usdt))
            r = cur.fetchone(); conn.commit(); return _row(cur, r)
    finally: release_conn(conn)

def get_risk_state():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM risk_state WHERE id=1")
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO risk_state (id) VALUES (1) RETURNING *")
                row = cur.fetchone(); conn.commit()
            return _row(cur, row)
    finally: release_conn(conn)

def update_risk_state(**kwargs):
    if not kwargs: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k}=%s" for k in kwargs)
            cur.execute(f"UPDATE risk_state SET {sets}, last_updated=NOW() WHERE id=1", list(kwargs.values()))
            conn.commit()
    finally: release_conn(conn)

def reset_daily_state_if_needed():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT trading_date FROM risk_state WHERE id=1")
            row = cur.fetchone()
            if row and row[0] != date.today():
                cur.execute("UPDATE risk_state SET trades_today=0,daily_pnl_usdt=0,trading_date=CURRENT_DATE WHERE id=1")
                conn.commit()
    finally: release_conn(conn)

def save_signal(symbol, timeframe, action, price, rsi, ema20, ema50):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO signals (symbol,timeframe,action,price,rsi,ema20,ema50) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (symbol,timeframe,action,price,rsi,ema20,ema50))
            sid = cur.fetchone()[0]; conn.commit(); return sid
    finally: release_conn(conn)

def open_trade(portfolio_id, symbol, timeframe, action, entry_price, stop_loss,
               take_profit, quantity, risk_amount_usdt, rsi, ema20, ema50,
               ai_decision=None, ai_confidence=None, ai_reasoning=None, signal_atr=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trades "
                "(portfolio_id,symbol,timeframe,action,entry_price,stop_loss,take_profit,"
                "quantity,risk_amount_usdt,signal_rsi,signal_ema20,signal_ema50,signal_atr,"
                "ai_decision,ai_confidence,ai_reasoning) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (portfolio_id,symbol,timeframe,action,entry_price,stop_loss,take_profit,
                 quantity,risk_amount_usdt,rsi,ema20,ema50,signal_atr,
                 ai_decision or "PENDING",ai_confidence,ai_reasoning))
            r = cur.fetchone(); conn.commit(); return _row(cur, r)
    finally: release_conn(conn)

def close_trade(trade_id, exit_price, status, pnl_usdt, pnl_eur, pnl_pct, fees_usdt):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE trades SET exit_price=%s,status=%s,pnl_usdt=%s,pnl_eur=%s,pnl_pct=%s,fees_usdt=%s,closed_at=NOW() WHERE id=%s RETURNING *",
                (exit_price,status,pnl_usdt,pnl_eur,pnl_pct,fees_usdt,trade_id))
            r = cur.fetchone(); conn.commit(); return _row(cur, r)
    finally: release_conn(conn)

def update_trade_sl(trade_id, new_sl):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE trades SET stop_loss=%s WHERE id=%s", (new_sl, trade_id))
            conn.commit()
    finally: release_conn(conn)

def get_open_trade(symbol=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if symbol:
                cur.execute("SELECT * FROM trades WHERE status='OPEN' AND symbol=%s ORDER BY opened_at DESC LIMIT 1",(symbol,))
            else:
                cur.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY opened_at DESC LIMIT 1")
            return _row(cur, cur.fetchone())
    finally: release_conn(conn)

def get_all_open_trades():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY opened_at DESC")
            return [_row(cur, r) for r in cur.fetchall()]
    finally: release_conn(conn)

def get_trades(limit=20, timeframe=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if timeframe:
                cur.execute("SELECT * FROM trades WHERE timeframe=%s ORDER BY created_at DESC LIMIT %s",(timeframe,limit))
            else:
                cur.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT %s",(limit,))
            return [_row(cur, r) for r in cur.fetchall()]
    finally: release_conn(conn)

def get_portfolio_stats():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT p.current_capital_usdt, p.initial_capital_usdt,
                COUNT(t.id) FILTER (WHERE t.status<>'OPEN') as total_trades,
                COUNT(t.id) FILTER (WHERE t.pnl_usdt>0) as trades_ganhos,
                COUNT(t.id) FILTER (WHERE t.pnl_usdt<=0 AND t.status<>'OPEN') as trades_perdidos,
                COALESCE(SUM(t.pnl_usdt) FILTER (WHERE t.status<>'OPEN'),0) as pnl_total_usdt,
                MAX(t.pnl_usdt) as melhor_trade_usdt, MIN(t.pnl_usdt) as pior_trade_usdt
                FROM portfolio p LEFT JOIN trades t ON t.portfolio_id=p.id
                WHERE p.is_active=TRUE
                GROUP BY p.current_capital_usdt, p.initial_capital_usdt""")
            row = cur.fetchone()
            if not row: return {}
            data  = _row(cur, row)
            total = data.get("total_trades") or 0; wins = data.get("trades_ganhos") or 0
            data["win_rate"]       = round((wins/total*100) if total>0 else 0, 2)
            data["pnl_total_usdt"] = float(data.get("pnl_total_usdt") or 0)
            cap  = float(data.get("current_capital_usdt") or 0)
            init = float(data.get("initial_capital_usdt") or 0)
            data["pnl_pct_total"]  = round(((cap-init)/init*100) if init>0 else 0, 2)
            return data
    finally: release_conn(conn)

def save_daily_summary(summary_date, stats_dict):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO daily_summaries
                (summary_date,total_signals,executed_trades,winning_trades,
                 losing_trades,pnl_usdt,pnl_eur,win_rate,closing_capital_usdt)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (summary_date) DO UPDATE SET
                executed_trades=EXCLUDED.executed_trades,
                winning_trades=EXCLUDED.winning_trades,
                losing_trades=EXCLUDED.losing_trades,
                pnl_usdt=EXCLUDED.pnl_usdt,
                win_rate=EXCLUDED.win_rate,
                closing_capital_usdt=EXCLUDED.closing_capital_usdt""",
                (summary_date,stats_dict.get("total_signals",0),stats_dict.get("executed_trades",0),
                 stats_dict.get("winning_trades",0),stats_dict.get("losing_trades",0),
                 stats_dict.get("pnl_usdt",0),stats_dict.get("pnl_eur",0),
                 stats_dict.get("win_rate",0),stats_dict.get("closing_capital_usdt",0)))
            conn.commit()
    finally: release_conn(conn)

def log(level, component, message, trade_id=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO system_logs (level,component,message,trade_id) VALUES (%s,%s,%s,%s)",
                        (level,component,message,trade_id))
            conn.commit()
    except Exception: pass
    finally: release_conn(conn)

def update_portfolio_capital(portfolio_id, delta_usdt):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE portfolio SET current_capital_usdt = current_capital_usdt + %s WHERE id=%s",
                (delta_usdt, portfolio_id))
            conn.commit()
    finally: release_conn(conn)
