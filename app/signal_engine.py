from app import database, fetcher, indicators
from app.config import (RSI_OVERSOLD, RSI_OVERBOUGHT, TIMEFRAMES,
                        ADX_MIN_TREND,
                        FUNDING_RATE_MAX_BUY, FUNDING_RATE_MIN_SELL)

def _get_4h_trend(symbol):
    candles = fetcher.get_klines(symbol, "4h", limit=60)
    if not candles or len(candles) < 52:
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

    ind   = indicators.calculate_all(candles)
    price = ind["current_price"]
    ema20 = ind["ema20"]; ema50 = ind["ema50"]
    prev20 = ind["prev_ema20"]; prev50 = ind["prev_ema50"]
    rsi   = ind["rsi"]; atr = ind["atr"]
    adx   = ind["adx"]

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

def check_all_timeframes(symbol):
    return {tf: detect_signal(symbol, tf) for tf in TIMEFRAMES}