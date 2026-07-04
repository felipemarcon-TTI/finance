from app import database
from app.config import (MAX_TRADES_PER_DAY, MAX_CONSECUTIVE_LOSSES,
                        MAX_CONCURRENT_POSITIONS, RISK_PER_TRADE_PCT,
                        MAX_POSITION_NOTIONAL_PCT, CASH_USAGE_CAP, DAILY_STOP_PCT,
                        DEFAULT_SL_PCT)


def _committed_notional(open_trades):
    return sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)


def check(signal, risk_state, portfolio):
    symbol = signal.get("symbol","")
    if risk_state.get("kill_switch_active"):
        return False, "Kill switch ativo"
    if database.get_open_trade(symbol):
        return False, f"Posicao aberta em {symbol}"
    open_trades = database.get_all_open_trades()
    if len(open_trades) >= MAX_CONCURRENT_POSITIONS:
        return False, f"Max {MAX_CONCURRENT_POSITIONS} posicoes abertas"
    if (risk_state.get("trades_today") or 0) >= MAX_TRADES_PER_DAY:
        return False, "Limite diario atingido"
    if (risk_state.get("consecutive_losses") or 0) >= MAX_CONSECUTIVE_LOSSES:
        return False, "Muitas perdas consecutivas"
    capital = float(portfolio.get("current_capital_usdt") or 0)
    # Stop diario sobre o capital do INICIO do dia (fallback: capital inicial do portfolio)
    day_base = float(risk_state.get("day_start_capital_usdt") or portfolio.get("initial_capital_usdt") or 0)
    if float(risk_state.get("daily_pnl_usdt") or 0) < -(day_base * DAILY_STOP_PCT):
        return False, f"Perda diaria de {DAILY_STOP_PCT:.0%} atingida"
    # Gate de caixa: notional total das posicoes abertas nao pode exceder CASH_USAGE_CAP
    committed = _committed_notional(open_trades)
    if capital * CASH_USAGE_CAP - committed <= capital * 0.02:
        return False, "Capital comprometido"
    return True, "OK"


def calculate_position_size(capital_usdt, entry_price, sl_pct=DEFAULT_SL_PCT, committed_usdt=0.0):
    """Sizing por risco com caps de notional (v3).
    Antes: cada posicao podia usar ate 95% do capital SEM descontar as abertas ->
    notional total de ate ~285% do capital (alavancagem oculta). Agora:
      quantity = min(risco/dist_SL, 20% do capital, caixa livre)."""
    risk_amount = capital_usdt * RISK_PER_TRADE_PCT
    quantity    = risk_amount / (entry_price * sl_pct)

    max_notional = min(
        capital_usdt * MAX_POSITION_NOTIONAL_PCT,
        max(0.0, capital_usdt * CASH_USAGE_CAP - committed_usdt),
    )
    max_quantity = max_notional / entry_price
    if quantity > max_quantity:
        quantity    = max_quantity
        risk_amount = quantity * entry_price * sl_pct

    return {
        "quantity":    quantity,
        "risk_amount": risk_amount,
    }
