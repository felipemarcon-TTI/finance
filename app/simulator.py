from app import fetcher, database
from app.config import (SLIPPAGE_PCT, FEE_PCT, RISK_PER_TRADE_PCT,
                        DEFAULT_SL_PCT, DEFAULT_TP_PCT,
                        ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER)

def execute_trade(signal, portfolio, ai_confidence=None, ai_reasoning=None):
    price=signal["price"]; action=signal["action"]; symbol=signal["symbol"]
    entry=price*(1+SLIPPAGE_PCT) if action=="BUY" else price*(1-SLIPPAGE_PCT)

    atr = signal.get("atr")
    if atr and atr > 0:
        sl_pct = (atr * ATR_SL_MULTIPLIER) / entry
        tp_pct = (atr * ATR_TP_MULTIPLIER) / entry
    else:
        sl_pct, tp_pct = DEFAULT_SL_PCT, DEFAULT_TP_PCT

    capital     = float(portfolio["current_capital_usdt"])
    risk_amount = capital * RISK_PER_TRADE_PCT
    qty         = risk_amount / (entry * sl_pct)

    sl = entry*(1-sl_pct) if action=="BUY" else entry*(1+sl_pct)
    tp = entry*(1+tp_pct) if action=="BUY" else entry*(1-tp_pct)

    trade = database.open_trade(
        portfolio_id=portfolio["id"], symbol=symbol, timeframe=signal["timeframe"],
        action=action, entry_price=entry, stop_loss=sl, take_profit=tp,
        quantity=qty, risk_amount_usdt=risk_amount,
        rsi=signal["rsi"], ema20=signal["ema20"], ema50=signal["ema50"],
        ai_decision="APPROVED" if ai_confidence is not None else "PENDING",
        ai_confidence=ai_confidence, ai_reasoning=ai_reasoning)
    rs = database.get_risk_state()
    database.update_risk_state(trades_today=(rs.get("trades_today") or 0)+1)
    return trade

def check_and_close_position(trade):
    symbol  = trade.get("symbol","BTCUSDT")
    current = fetcher.get_current_price(symbol)
    if not current: return None
    action=trade["action"]; sl=float(trade["stop_loss"]); tp=float(trade["take_profit"])
    status=None
    if action=="BUY":
        if current<=sl: status="CLOSED_SL"
        elif current>=tp: status="CLOSED_TP"
    else:
        if current>=sl: status="CLOSED_SL"
        elif current<=tp: status="CLOSED_TP"
    if not status: return None
    entry=float(trade["entry_price"]); qty=float(trade["quantity"])
    eur_rate=fetcher.get_eur_usdt_rate() or 1.0; fees=qty*current*FEE_PCT
    pnl_usdt=((current-entry) if action=="BUY" else (entry-current))*qty-fees
    closed=database.close_trade(trade["id"],current,status,pnl_usdt,
                                 pnl_usdt/eur_rate,(pnl_usdt/(entry*qty))*100,fees)
    rs=database.get_risk_state()
    database.update_risk_state(
        daily_pnl_usdt=float(rs.get("daily_pnl_usdt") or 0)+pnl_usdt,
        consecutive_losses=0 if pnl_usdt>0 else (rs.get("consecutive_losses") or 0)+1)
    return closed
