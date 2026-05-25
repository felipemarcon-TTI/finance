from app.config import MAX_TRADES_PER_DAY, MAX_CONSECUTIVE_LOSSES, RISK_PER_TRADE_PCT, DEFAULT_SL_PCT, DEFAULT_TP_PCT

def check(signal, risk_state, portfolio):
    if risk_state.get("kill_switch_active"):        return False, "Kill switch ativo"
    if risk_state.get("has_open_position"):         return False, "Ja existe posicao aberta"
    if (risk_state.get("trades_today") or 0) >= MAX_TRADES_PER_DAY: return False, "Limite diario atingido"
    if (risk_state.get("consecutive_losses") or 0) >= MAX_CONSECUTIVE_LOSSES: return False, "Muitas perdas consecutivas"
    if float(risk_state.get("daily_pnl_usdt") or 0) < -(float(portfolio.get("initial_capital_usdt") or 0)*0.05):
        return False, "Perda diaria de 5% atingida"
    return True, "OK"

def calculate_position_size(capital_usdt, entry_price, sl_pct=DEFAULT_SL_PCT):
    risk_amount = capital_usdt * RISK_PER_TRADE_PCT
    return {"quantity":risk_amount/(entry_price*sl_pct),"risk_amount":risk_amount,
            "stop_loss":entry_price*(1-sl_pct),"take_profit":entry_price*(1+DEFAULT_TP_PCT)}
