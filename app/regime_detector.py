import time as _time
from app import indicators
from app.config import REGIME_BULL_THRESHOLD

_cache = {"regime": "BEAR", "ts": 0.0}
_TTL   = 3600


def get_regime(candle_store: dict) -> str:
    now = _time.monotonic()
    if now - _cache["ts"] < _TTL and _cache["ts"] > 0:
        return _cache["regime"]
    if not candle_store:
        return _cache["regime"]

    bullish = 0
    total   = 0
    for candles in candle_store.values():
        if len(candles) < 52:
            continue
        ind = indicators.calculate_all(candles)
        e20 = ind.get("ema20")
        e50 = ind.get("ema50")
        if e20 and e50:
            total += 1
            if e20 > e50:
                bullish += 1

    regime = "BULL" if (total > 0 and bullish / total >= REGIME_BULL_THRESHOLD) else "BEAR"
    _cache.update({"regime": regime, "ts": now})
    return regime