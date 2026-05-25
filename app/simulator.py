from app import fetcher, database, risk_engine
from app.config import SYMBOL, SLIPPAGE_PCT, FEE_PCT, DEFAULT_SL_PCT, DEFAULT_TP_PCT

def execute_trade(signal, portfolio):
    price=signal["price"]; action=signal["action"]
    entry=price*(1+SLIPPAGE_PCT) if action=="BUY" else price*(1-SLIPPAGE_PCT)
    pos=risk_engine.calculate_position_size(float(portfolio["current_capital_usdt"]),entry,DEFAULT_SL_PCT)
    if action=="SELL": pos["stop_loss"]=entry*(1+DEFAULT_SL_PCT); pos["take_profit"]=entry*(1-DEFAULT_TP_PCT)
    trade=database.open_trade(portfolio_id=portfolio["id"],timeframe=signal["timeframe"],action=action,
        entry_price=entry,stop_loss=pos["stop_loss"],take_profit=pos["take_profit"],
        quantity=pos["quantity"],risk_amount_usdt=pos["risk_amount"],
        rsi=signal["rsi"],ema20=signal["ema20"],ema50=signal["ema50"])
    rs=database.get_risk_state()
    database.update_risk_state(has_open_position=True,current_trade_id=trade["id"],
        trades_today=(rs.get("trades_today") or 0)+1)
    return trade

def check_and_close_position(trade):
    current=fetcher.get_current_price(SYMBOL)
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
    eur_rate=fetcher.get_eur_usdt_rate() or 1.0; exit_fees=qty*current*FEE_PCT
    pnl_usdt=((current-entry) if action=="BUY" else (entry-current))*qty-exit_fees
    closed=database.close_trade(trade["id"],current,status,pnl_usdt,pnl_usdt/(eur_rate),(pnl_usdt/(entry*qty))*100,exit_fees)
    rs=database.get_risk_state()
    database.update_risk_state(has_open_position=False,current_trade_id=None,
        daily_pnl_usdt=float(rs.get("daily_pnl_usdt") or 0)+pnl_usdt,
        consecutive_losses=0 if pnl_usdt>0 else (rs.get("consecutive_losses") or 0)+1)
    return closed
