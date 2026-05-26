import pandas as pd
from app.config import EMA_SHORT, EMA_LONG, RSI_PERIOD, ATR_PERIOD

def calculate_ema(closes, period):
    ema = pd.Series(closes).ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1]), float(ema.iloc[-2])

def calculate_rsi(closes, period=RSI_PERIOD):
    s     = pd.Series(closes)
    delta = s.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return float((100 - 100/(1+rs)).iloc[-1])

def calculate_atr(candles, period=ATR_PERIOD):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return float(pd.Series(trs).ewm(span=period, adjust=False).mean().iloc[-1])

def calculate_volume_ratio(candles, period=20):
    vols = [c["volume"] for c in candles]
    current = vols[-1]
    avg = sum(vols[-period-1:-1]) / period if len(vols) > period else 1.0
    return current, avg, round(current/avg, 2) if avg > 0 else 0.0

def calculate_all(candles):
    closes        = [c["close"] for c in candles]
    ema20, prev20 = calculate_ema(closes, EMA_SHORT)
    ema50, prev50 = calculate_ema(closes, EMA_LONG)
    atr           = calculate_atr(candles)
    _, _, vol_ratio = calculate_volume_ratio(candles)
    return {"current_price":closes[-1], "ema20":ema20, "ema50":ema50,
            "prev_ema20":prev20, "prev_ema50":prev50,
            "rsi":calculate_rsi(closes), "atr":atr, "volume_ratio":vol_ratio}
