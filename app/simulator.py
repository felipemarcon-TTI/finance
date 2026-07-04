from app import database, fetcher
from app.config import (SLIPPAGE_PCT, FEE_PCT, TRADING_MODE,
                        ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER, TRAILING_ENABLED)
from app.risk_engine import calculate_position_size, _committed_notional

# NOTA (v3): SELL = short SINTETICO sobre precos spot (paper trading). Operar short em
# dinheiro real exigiria conta de futuros USDT-M (margem, funding pago/recebido, risco
# de liquidacao) - fora do escopo do modo simulation.

def execute_trade(signal, portfolio, ai_confidence=None, ai_reasoning=None):
    action    = signal["action"]
    symbol    = signal["symbol"]
    timeframe = signal["timeframe"]
    raw_price = signal["price"]
    atr       = signal.get("atr", 0)
    sl_mult   = signal.get("sl_mult", ATR_SL_MULTIPLIER)
    tp_mult   = signal.get("tp_mult", ATR_TP_MULTIPLIER)

    entry = raw_price * (1 + SLIPPAGE_PCT) if action == "BUY" else raw_price * (1 - SLIPPAGE_PCT)

    if atr and atr > 0:
        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult
        stop_loss   = entry - sl_dist if action == "BUY" else entry + sl_dist
        take_profit = entry + tp_dist if action == "BUY" else entry - tp_dist
        sl_pct = sl_dist / entry
    else:
        from app.config import DEFAULT_SL_PCT, DEFAULT_TP_PCT
        sl_pct = DEFAULT_SL_PCT
        stop_loss   = entry * (1 - sl_pct) if action == "BUY" else entry * (1 + sl_pct)
        take_profit = entry * (1 + DEFAULT_TP_PCT) if action == "BUY" else entry * (1 - DEFAULT_TP_PCT)

    capital_usdt = float(portfolio["current_capital_usdt"])
    committed = _committed_notional(database.get_all_open_trades())
    pos = calculate_position_size(capital_usdt, entry, sl_pct, committed_usdt=committed)
    if pos["quantity"] <= 0:
        return None

    trade = database.open_trade(
        portfolio_id     = portfolio["id"],
        symbol           = symbol,
        timeframe        = timeframe,
        action           = action,
        entry_price      = entry,
        stop_loss        = stop_loss,
        take_profit      = take_profit,
        quantity         = pos["quantity"],
        risk_amount_usdt = pos["risk_amount"],
        rsi              = signal.get("rsi"),
        ema20            = signal.get("ema20"),
        ema50            = signal.get("ema50"),
        ai_decision      = "APPROVED" if ai_confidence else "PENDING",
        ai_confidence    = ai_confidence,
        ai_reasoning     = ai_reasoning,
        signal_atr       = atr if atr and atr > 0 else None,
        signal_sl_dist   = abs(entry - stop_loss),  # distancia de stop original (fixa p/ o trailing)
    )

    risk = database.get_risk_state()
    database.update_risk_state(
        has_open_position = True,
        current_trade_id  = trade["id"],
        trades_today      = (risk.get("trades_today") or 0) + 1,
    )

    regime = signal.get("regime", "?")
    print(f"[sim] TRADE OPEN {action} {symbol} @ {entry:.4f} SL={stop_loss:.4f} TP={take_profit:.4f} qty={pos['quantity']:.6f} regime={regime}")
    return trade

def check_and_close_position(trade):
    symbol  = trade.get("symbol", "BTCUSDT")
    action  = trade["action"]
    entry   = float(trade["entry_price"])
    sl      = float(trade["stop_loss"])
    tp      = float(trade["take_profit"])
    qty     = float(trade["quantity"])
    port_id = trade["portfolio_id"]

    current = fetcher.get_current_price(symbol)
    if current is None:
        return None

    signal_atr = float(trade.get("signal_atr") or 0)
    # v3: trailing DESATIVADO por padrao (TRAILING_ENABLED=False). No backtest 2025-2026,
    # o trailing/breakeven convertia winners em scratch-losses; SL/TP fixos e largos
    # (2.5/5.0 ATR) foram mais robustos. Codigo mantido para reativacao futura.
    if TRAILING_ENABLED and signal_atr > 0:
        # Gap do trailing = distancia de stop ORIGINAL (fixa), nao a atual.
        # Antes usava abs(entry - stop_loss), mas stop_loss eh movido pelo trailing:
        # apos o breakeven (stop_loss==entry) o gap virava 0 e o trailing colava no
        # preco, fechando o trade ao tocar +2 ATR (TP de 3 ATR nunca era atingido).
        sl_dist = float(trade.get("signal_sl_dist") or 0) or (signal_atr * ATR_SL_MULTIPLIER)
        if action == "BUY":
            if current >= entry + 2 * signal_atr:
                new_sl = max(sl, current - sl_dist)
            elif current >= entry + signal_atr:
                new_sl = max(sl, entry)
            else:
                new_sl = None
            if new_sl and new_sl > sl:
                database.update_trade_sl(trade["id"], new_sl)
                sl = new_sl
        else:
            if current <= entry - 2 * signal_atr:
                new_sl = min(sl, current + sl_dist)
            elif current <= entry - signal_atr:
                new_sl = min(sl, entry)
            else:
                new_sl = None
            if new_sl and new_sl < sl:
                database.update_trade_sl(trade["id"], new_sl)
                sl = new_sl

    closed = False
    if action == "BUY":
        if current <= sl:
            status = "CLOSED_SL"; closed = True
        elif current >= tp:
            status = "CLOSED_TP"; closed = True
    else:
        if current >= sl:
            status = "CLOSED_SL"; closed = True
        elif current <= tp:
            status = "CLOSED_TP"; closed = True

    if not closed:
        return None

    fees = qty * current * FEE_PCT
    gross = (current - entry) * qty if action == "BUY" else (entry - current) * qty
    pnl_usdt = gross - fees - qty * entry * FEE_PCT

    eur_rate = fetcher.get_eur_usdt_rate() or 1.0
    pnl_eur  = pnl_usdt / eur_rate
    pnl_pct  = (pnl_usdt / (entry * qty)) * 100 if entry * qty > 0 else 0

    closed_trade = database.close_trade(trade["id"], current, status, pnl_usdt, pnl_eur, pnl_pct, fees)
    database.update_portfolio_capital(port_id, pnl_usdt)

    risk = database.get_risk_state()
    consec = risk.get("consecutive_losses") or 0
    consec = 0 if pnl_usdt > 0 else consec + 1
    database.update_risk_state(
        has_open_position  = False,
        current_trade_id   = None,
        consecutive_losses = consec,
        daily_pnl_usdt     = (risk.get("daily_pnl_usdt") or 0) + pnl_usdt,
    )

    print(f"[sim] TRADE CLOSED {status} {symbol} @ {current:.4f} PnL={pnl_usdt:.2f} USDT")
    return closed_trade