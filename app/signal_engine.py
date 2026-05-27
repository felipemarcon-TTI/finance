import time as _time
from app import database, fetcher, indicators
from app.config import (RSI_OVERSOLD, RSI_OVERBOUGHT, TIMEFRAMES,
                        ADX_MIN_TREND,
                        FUNDING_RATE_MAX_BUY, FUNDING_RATE_MIN_SELL)

_4h_cache: dict = {}
_4H_TTL = 3600

_RSI_MR_OVERSOLD  = 30
_RSI_MR_OVERBOUGHT = 70


def _get_4h_candles(symbol: str) -> list:
    now = _time.monotonic()
    if symbol in _4h_cache:
        ts, candles = _4h_cache[symbol]
        if now - ts < _4H_TTL:
            return candles
    candles = fetcher.get_klines(symbol, "4h", limit=60)
    if candles:
        _4h_cache[symbol] = (now, candles)
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


def detect_signal(symbol, timeframe):
    candles = fetcher.get_klines(symbol, timeframe, limit=100)
    if not candles or len(candles) < 55:
        return None

    ind    = indicators.calculate_all(candles)
    price  = ind["current_price"]
    ema20  = ind["ema20"]; ema50  = ind["ema50"]
    prev20 = ind["prev_ema20"]; prev50 = ind["prev_ema50"]
    rsi    = ind["rsi"]; atr = ind["atr"]
    adx    = ind["adx"]

    action = None
    if prev20 <= prev50 and ema20 > ema50 and RSI_OVERSOLD < rsi < RSI_OVERBOUGHT:
        action = "BUY"
    elif prev20 >= prev50 and ema20 < ema50 and RSI_OVERSOLD < rsi < RSI_OVERBOUGHT:
        action = "SELL"
    if not action:
        return None

    if adx < ADX_MIN_TREND:
        return None

    trend_4h = "NEUTRAL"
    if timeframe in ("1h", "15m"):
        trend_4h = _get_4h_trend(symbol)
        if action == "BUY"  and trend_4h == "DOWN":
            return None
        if action == "SELL" and trend_4h == "UP":
            return None

    funding = fetcher.get_funding_rate(symbol)
    if funding is not None:
        if action == "BUY"  and funding >  FUNDING_RATE_MAX_BUY:
            return None
        if action == "SELL" and funding <  FUNDING_RATE_MIN_SELL:
            return None

    database.save_signal(symbol, timeframe, action, price, rsi, ema20, ema50)
    return {
        "action": action, "symbol": symbol, "timeframe": timeframe,
        "price": price, "rsi": rsi, "ema20": ema20, "ema50": ema50,
        "atr": atr, "adx": adx, "funding": funding, "trend_4h": trend_4h,
    }


def detect_mean_reversion(symbol: str):
    candles = _get_4h_candles(symbol)
    if len(candles) < 20:
        return None

    ind   = indicators.calculate_all(candles)
    rsi   = ind["rsi"]
    price = ind["current_price"]
    ema20 = ind["ema20"]; ema50 = ind["ema50"]
    atr   = ind.get("atr")

    action = None
    if rsi < _RSI_MR_OVERSOLD:
        action = "BUY"
    elif rsi > _RSI_MR_OVERBOUGHT:
        action = "SELL"
    if not action:
        return None

    # Skip capitulation: RSI<30 in downtrend = still falling, not reverting
    trend = _get_4h_trend(symbol)
    if action == "BUY"  and trend == "DOWN":
        return None
    if action == "SELL" and trend == "UP":
        return None

    funding = fetcher.get_funding_rate(symbol)
    if funding is not None:
        if action == "BUY"  and funding >  FUNDING_RATE_MAX_BUY:
            return None
        if action == "SELL" and funding <  FUNDING_RATE_MIN_SELL:
            return None

    database.save_signal(symbol, "4h_mr", action, price, rsi, ema20, ema50)
    return {
        "action": action, "symbol": symbol, "timeframe": "4h_mr",
        "price": price, "rsi": rsi, "ema20": ema20, "ema50": ema50,
        "atr": atr, "funding": funding, "trend_4h": trend,
        "strategy": "mean_reversion",
    }


def check_all_timeframes(symbol):
    result = {tf: detect_signal(symbol, tf) for tf in TIMEFRAMES}
    result["4h_mr"] = detect_mean_reversion(symbol)
    return result