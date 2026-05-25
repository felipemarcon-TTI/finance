import pandas as pd
from app.config import EMA_SHORT, EMA_LONG, RSI_PERIOD

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
    return float((100 - 100/(1 + avg_gain/avg_loss)).iloc[-1])

def calculate_all(candles):
    closes        = [c["close"] for c in candles]
    ema20, prev20 = calculate_ema(closes, EMA_SHORT)
    ema50, prev50 = calculate_ema(closes, EMA_LONG)
    return {"current_price":closes[-1],"ema20":ema20,"ema50":ema50,
            "prev_ema20":prev20,"prev_ema50":prev50,"rsi":calculate_rsi(closes)}
