import time as _time
from app import database, fetcher, indicators, regime_detector
from app.config import (RSI_OVERSOLD, RSI_OVERBOUGHT, TIMEFRAMES,
                        ADX_MIN_TREND,
                        FUNDING_RATE_MAX_BUY, FUNDING_RATE_MIN_SELL,
                        STRATEGY_PRESETS, USE_MEAN_REVERSION)

# v3: sinais avaliados SOMENTE em candles fechados (drop_forming=True) e apenas nos
# boundaries de cada timeframe (scheduler._due_timeframes). O candle em formacao
# causava flicker de cruzamento e divergencia live<->backtest.

_4h_cache: dict = {}
_4H_TTL = 3600
_4h_candle_store: dict = {}


def refresh_4h_cache():
    """Invalidacao ativa no boundary de 4h (chamada pelo scheduler)."""
    _4h_cache.clear()


def _get_4h_candles(symbol: str) -> list:
    now = _time.monotonic()
    if symbol in _4h_cache:
        ts, candles = _4h_cache[symbol]
        if now - ts < _4H_TTL:
            return candles
    candles = fetcher.get_klines(symbol, "4h", limit=61, drop_forming=True)
    if candles:
        _4h_cache[symbol] = (now, candles)
        _4h_candle_store[symbol] = candles
    return candles or []


def _get_4h_trend(symbol):
    candles = _get_4h_candles(symbol)
    if len(candles) < 52:
        return "NEUTRAL"
    ind = indicators.calculate_all(candles)
    if ind["ema20"] > ind["ema50"]:
        return "UP"
    if ind["ema20"] < ind["ema50"]:
        return "DOWN"
    return "NEUTRAL"


# ---- regras puras (importadas pelo backtest em scripts/backtest.py p/ paridade) ----

def trend_rule(ind, adx_min=ADX_MIN_TREND, rsi_lo=RSI_OVERSOLD, rsi_hi=RSI_OVERBOUGHT):
    """Cruzamento EMA_SHORT x EMA_LONG (v3: 50x100, chaves ema_s/ema_l) no candle fechado
    + banda RSI + ADX minimo. Retorna 'BUY' | 'SELL' | None.
    Simetrica: SELL (death cross) roda nos dois regimes.
    NOTA: ema20/ema50 (fixas) ficam para o filtro de tendencia 4h e o regime detector."""
    if ind["prev_ema_s"] <= ind["prev_ema_l"] and ind["ema_s"] > ind["ema_l"] \
            and rsi_lo < ind["rsi"] < rsi_hi:
        action = "BUY"
    elif ind["prev_ema_s"] >= ind["prev_ema_l"] and ind["ema_s"] < ind["ema_l"] \
            and rsi_lo < ind["rsi"] < rsi_hi:
        action = "SELL"
    else:
        return None
    if ind["adx"] < adx_min:
        return None
    return action


def mr_rule(ind, preset):
    """RSI extremo no 4h (mean-reversion). Retorna 'BUY' | 'SELL' | None."""
    if ind["rsi"] < preset["mr_rsi_os"]:
        return "BUY"
    if ind["rsi"] > preset["mr_rsi_ob"]:
        return "SELL"
    return None


def _funding_blocks(action, funding):
    if funding is None:
        return False
    if action == "BUY" and funding > FUNDING_RATE_MAX_BUY:
        return True
    if action == "SELL" and funding < FUNDING_RATE_MIN_SELL:
        return True
    return False


def detect_signal(symbol, timeframe):
    # EMA_LONG=100 exige historico maior: 120 candles fechados, minimo 105
    candles = fetcher.get_klines(symbol, timeframe, limit=121, drop_forming=True)
    if not candles or len(candles) < 105:
        return None

    ind    = indicators.calculate_all(candles)
    action = trend_rule(ind)
    if not action:
        return None

    trend_4h = "NEUTRAL"
    if timeframe in ("1h", "15m"):
        trend_4h = _get_4h_trend(symbol)
        if action == "BUY"  and trend_4h == "DOWN":
            return None
        if action == "SELL" and trend_4h == "UP":
            return None

    funding = fetcher.get_funding_rate(symbol)
    if _funding_blocks(action, funding):
        return None

    regime = regime_detector.get_regime(_4h_candle_store)
    preset = STRATEGY_PRESETS[regime]
    price  = ind["current_price"]
    # grava as EMAs DO SINAL (50/100) nas colunas ema20/ema50 do registro
    database.save_signal(symbol, timeframe, action, price, ind["rsi"], ind["ema_s"], ind["ema_l"])
    return {
        "action": action, "symbol": symbol, "timeframe": timeframe,
        "price": price, "rsi": ind["rsi"], "ema20": ind["ema_s"], "ema50": ind["ema_l"],
        "atr": ind["atr"], "adx": ind["adx"], "funding": funding, "trend_4h": trend_4h,
        "regime": regime,
        "sl_mult": preset["sl_mult"], "tp_mult": preset["tp_mult"],
    }


def detect_mean_reversion(symbol: str):
    candles = _get_4h_candles(symbol)
    if len(candles) < 52:
        return None

    regime = regime_detector.get_regime(_4h_candle_store)
    preset = STRATEGY_PRESETS[regime]

    ind    = indicators.calculate_all(candles)
    action = mr_rule(ind, preset)
    if not action:
        return None

    trend = "UP" if ind["ema20"] > ind["ema50"] else ("DOWN" if ind["ema20"] < ind["ema50"] else "NEUTRAL")
    if action == "BUY"  and trend == "DOWN":
        return None
    if action == "SELL" and trend == "UP":
        return None

    funding = fetcher.get_funding_rate(symbol)
    if _funding_blocks(action, funding):
        return None

    price = ind["current_price"]
    database.save_signal(symbol, "4h_mr", action, price, ind["rsi"], ind["ema20"], ind["ema50"])
    return {
        "action": action, "symbol": symbol, "timeframe": "4h_mr",
        "price": price, "rsi": ind["rsi"], "ema20": ind["ema20"], "ema50": ind["ema50"],
        "atr": ind.get("atr"), "funding": funding, "trend_4h": trend,
        "strategy": "mean_reversion", "regime": regime,
        "sl_mult": preset["sl_mult"], "tp_mult": preset["tp_mult"],
    }


def check_all_timeframes(symbol, due_tfs=None):
    """v3: avalia apenas os timeframes cujo candle acabou de fechar (due_tfs).
    due_tfs=None mantem compatibilidade (avalia todos)."""
    due = set(due_tfs) if due_tfs is not None else set(TIMEFRAMES) | {"4h"}
    result = {}
    if USE_MEAN_REVERSION and "4h" in due:
        result["4h_mr"] = detect_mean_reversion(symbol)
    for tf in TIMEFRAMES:
        if tf in due:
            result[tf] = detect_signal(symbol, tf)
    return result
