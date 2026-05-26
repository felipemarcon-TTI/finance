from app import fetcher, indicators, database
from app.config import (TIMEFRAMES, RSI_OVERBOUGHT, RSI_OVERSOLD,
                        VOLUME_FILTER_MULTIPLIER, FUNDING_RATE_MAX_BUY, FUNDING_RATE_MIN_SELL)

def _get_4h_trend(symbol):
    candles = fetcher.get_klines(symbol, "4h", 60)
    if not candles or len(candles) < 55: return "NEUTRAL"
    closes = [c["close"] for c in candles]
    ema20, _ = indicators.calculate_ema(closes, 20)
    ema50, _ = indicators.calculate_ema(closes, 50)
    if ema20 > ema50: return "UP"
    if ema20 < ema50: return "DOWN"
    return "NEUTRAL"

def detect_signal(symbol, timeframe):
    candles = fetcher.get_klines(symbol, timeframe)
    if not candles or len(candles) < 60: return None
    ind = indicators.calculate_all(candles)
    ema20,ema50,prev20,prev50 = ind["ema20"],ind["ema50"],ind["prev_ema20"],ind["prev_ema50"]
    rsi,price,atr = ind["rsi"],ind["current_price"],ind["atr"]
    vol_ratio = ind["volume_ratio"]

    action = None
    if prev20<=prev50 and ema20>ema50 and RSI_OVERSOLD<rsi<RSI_OVERBOUGHT: action="BUY"
    elif prev20>=prev50 and ema20<ema50 and RSI_OVERSOLD<rsi<RSI_OVERBOUGHT: action="SELL"
    if not action: return None

    if vol_ratio < VOLUME_FILTER_MULTIPLIER: return None

    trend_4h = "N/A"
    if timeframe in ("1h","15m"):
        trend_4h = _get_4h_trend(symbol)
        if action=="BUY"  and trend_4h=="DOWN": return None
        if action=="SELL" and trend_4h=="UP":   return None

    funding = fetcher.get_funding_rate(symbol)
    if funding is not None:
        if action=="BUY"  and funding >  FUNDING_RATE_MAX_BUY:  return None
        if action=="SELL" and funding <  FUNDING_RATE_MIN_SELL:  return None

    database.save_signal(symbol,timeframe,action,price,rsi,ema20,ema50)
    return {"action":action,"symbol":symbol,"timeframe":timeframe,
            "price":price,"rsi":rsi,"ema20":ema20,"ema50":ema50,
            "atr":atr,"vol_ratio":vol_ratio,"funding":funding,"trend_4h":trend_4h}

def check_all_timeframes(symbol):
    return {tf: detect_signal(symbol, tf) for tf in TIMEFRAMES}
