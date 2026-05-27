import time
from datetime import datetime, timezone, date
from app import database, fetcher, signal_engine, simulator, telegram_bot, ai_filter
from app.config import (INITIAL_CAPITAL_EUR, LOOP_INTERVAL_SECONDS, MONITOR_INTERVAL_SECONDS,
                        TRADING_MODE, TOP_SYMBOLS_COUNT, SYMBOLS_OVERRIDE, USE_AI_FILTER)
from app.risk_engine import check as risk_check

class Scheduler:
    def __init__(self):
        self.portfolio    = None
        self._last_monitor = 0
        self._summary_done = None
        self._symbols      = []
        self._symbols_date = None
        self._tick_count   = 0

    def _refresh_symbols(self):
        today = date.today()
        if self._symbols_date == today and self._symbols: return
        if SYMBOLS_OVERRIDE:
            self._symbols = [s.strip() for s in SYMBOLS_OVERRIDE.split(",") if s.strip()]
        else:
            self._symbols = fetcher.get_top_symbols_by_volume(TOP_SYMBOLS_COUNT)
        self._symbols_date = today
        database.log("INFO", "scheduler", f"{len(self._symbols)} symbols carregados: {','.join(self._symbols[:5])}")

    def run(self):
        database.init_db()
        self.portfolio = database.get_active_portfolio()
        if not self.portfolio:
            rate  = fetcher.get_eur_usdt_rate() or 1.0
            usdt  = INITIAL_CAPITAL_EUR * rate
            self.portfolio = database.create_portfolio(INITIAL_CAPITAL_EUR, usdt, rate)
        database.get_risk_state()
        self._refresh_symbols()
        telegram_bot.start()
        database.log("INFO", "scheduler", "Bot iniciado")
        telegram_bot.notify(f"Bot iniciado | EUR{INITIAL_CAPITAL_EUR} | {TRADING_MODE.upper()} | {len(self._symbols)} pares")
        while True:
            try:
                self._tick()
            except Exception as e:
                database.log("ERROR", "scheduler", f"Tick error: {e}")
            time.sleep(LOOP_INTERVAL_SECONDS)

    def _tick(self):
        self._tick_count += 1
        database.reset_daily_state_if_needed()
        self._refresh_symbols()
        self.portfolio = database.get_active_portfolio()

        # Heartbeat every 10 ticks (~10 min)
        if self._tick_count % 10 == 0:
            rs  = database.get_risk_state()
            cap = float(self.portfolio.get("current_capital_usdt", 0)) if self.portfolio else 0
            open_n = len(database.get_all_open_trades())
            database.log("INFO", "heartbeat",
                f"tick={self._tick_count} | symbols={len(self._symbols)} | "
                f"open={open_n} | trades_hoje={rs.get('trades_today',0)} | "
                f"capital=${cap:.0f}")

        now = time.time()
        if (now - self._last_monitor) >= MONITOR_INTERVAL_SECONDS:
            self._last_monitor = now
            for ot in database.get_all_open_trades():
                closed = simulator.check_and_close_position(ot)
                if closed:
                    telegram_bot.notify_trade_closed(closed)
                    database.log("INFO", "sim",
                        f"Closed {closed['id']} {closed.get('symbol','')} {closed['status']} pnl=${float(closed.get('pnl_usdt') or 0):.2f}")

        rs = database.get_risk_state()
        if not rs.get("kill_switch_active"):
            for symbol in self._symbols:
                for tf, sig in signal_engine.check_all_timeframes(symbol).items():
                    if sig:
                        self._process_signal(sig)
                        break

        utc   = datetime.now(timezone.utc)
        today = date.today()
        if utc.hour == 23 and utc.minute == 59 and self._summary_done != today:
            self._summary_done = today
            self._daily_summary()

    def _process_signal(self, signal):
        sym = signal["symbol"]
        database.log("INFO", "signal",
            f"{sym} {signal['action']} {signal['timeframe']} "
            f"${signal['price']:.4f} ADX:{signal.get('adx',0):.1f} 4h:{signal.get('trend_4h','?')}")

        sentiment = fetcher.get_cryptopanic_sentiment(sym)

        ai_confidence = None
        ai_reasoning  = None
        if USE_AI_FILTER:
            approved, ai_confidence, ai_reasoning = ai_filter.validate(signal, sentiment)
            database.log("INFO", "ai",
                f"{sym}: {'OK' if approved else 'REJECTED'} {ai_confidence}% {ai_reasoning}")
            if not approved:
                telegram_bot.notify_signal(signal)
                telegram_bot.notify_trade_opened(None, False, f"AI ({ai_confidence}%): {ai_reasoning}")
                return

        telegram_bot.notify_signal(signal)
        rs  = database.get_risk_state()
        ok, reason = risk_check(signal, rs, self.portfolio)
        if not ok:
            database.log("INFO", "risk", f"{sym}: {reason}")
            telegram_bot.notify_trade_opened(None, False, reason)
            return

        trade = simulator.execute_trade(signal, self.portfolio, ai_confidence, ai_reasoning)
        telegram_bot.notify_trade_opened(trade, True, "OK")
        database.log("INFO", "sim",
            f"Opened {trade['id']} {sym} {signal['action']} ${float(trade['entry_price']):.4f}")

    def _daily_summary(self):
        s = database.get_portfolio_stats()
        database.save_daily_summary(date.today(), {
            "pnl_usdt":           s.get("pnl_total_usdt", 0),
            "win_rate":           s.get("win_rate", 0),
            "total_trades":       s.get("total_trades", 0),
            "winning_trades":     s.get("trades_ganhos", 0),
            "losing_trades":      s.get("trades_perdidos", 0),
            "closing_capital_usdt": s.get("current_capital_usdt", 0),
        })
        telegram_bot.notify_daily_summary(s)
        database.log("INFO", "scheduler", f"Daily summary: pnl=${float(s.get('pnl_total_usdt',0)):.2f}")