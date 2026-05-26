import pandas as pd
from app.config import RSI_PERIOD, EMA_SHORT, EMA_LONG, ATR_PERIOD, ADX_PERIOD

def calculate_ema(closes, period):
    s = pd.Series(closes)
    ema = s.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1]), float(ema.iloc[-2])

def calculate_rsi(closes, period=RSI_PERIOD):
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_atr(candles, period=ATR_PERIOD):
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]; l = candles[i]["low"]; pc = candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = pd.Series(trs).ewm(alpha=1/period, adjust=False).mean()
    return float(atr.iloc[-1])

def calculate_adx(candles, period=ADX_PERIOD):
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        up   = candles[i]["high"]  - candles[i-1]["high"]
        down = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(up   if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(candles[i]["high"] - candles[i]["low"],
                       abs(candles[i]["high"] - candles[i-1]["close"]),
                       abs(candles[i]["low"]  - candles[i-1]["close"])))
    alpha     = 1.0 / period
    smooth_tr = pd.Series(trs).ewm(alpha=alpha, adjust=False).mean()
    plus_di   = 100 * pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean() / smooth_tr
    minus_di  = 100 * pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean() / smooth_tr
    denom     = (plus_di + minus_di).replace(0, float("nan"))
    dx        = (abs(plus_di - minus_di) / denom * 100).fillna(0)
    adx       = dx.ewm(alpha=alpha, adjust=False).mean()
    return float(adx.iloc[-1])

def calculate_volume_ratio(candles, period=20):
    vols = [c["volume"] for c in candles]
    current = vols[-1]
    avg = sum(vols[-period-1:-1]) / period if len(vols) >= period + 1 else current
    return current, avg, (current / avg if avg > 0 else 1.0)

def calculate_all(candles):
    closes  = [c["close"]  for c in candles]
    ema20, prev_ema20 = calculate_ema(closes, EMA_SHORT)
    ema50, prev_ema50 = calculate_ema(closes, EMA_LONG)
    rsi      = calculate_rsi(closes)
    atr      = calculate_atr(candles)
    adx      = calculate_adx(candles)
    _, _, vol_ratio = calculate_volume_ratio(candles)
    return {
        "current_price": closes[-1],
        "ema20": ema20, "ema50": ema50,
        "prev_ema20": prev_ema20, "prev_ema50": prev_ema50,
        "rsi": rsi, "atr": atr, "adx": adx, "volume_ratio": vol_ratio,
    }
