import time as _time
from app import indicators
from app.config import REGIME_BULL_THRESHOLD, REGIME_BEAR_THRESHOLD

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
        # breadth SEMPRE em EMA20/EMA50 fixas (independe do par de EMAs do sinal)
        e20 = ind.get("ema20")
        e50 = ind.get("ema50")
        if e20 and e50:
            total += 1
            if e20 > e50:
                bullish += 1

    if total == 0:
        return _cache["regime"]

    # Histerese anti flip-flop (v3): BEAR->BULL exige ratio >= 0.60;
    # BULL->BEAR exige ratio < 0.45; entre os dois, mantem o regime anterior.
    ratio = bullish / total
    prev  = _cache["regime"]
    if prev == "BEAR" and ratio >= REGIME_BULL_THRESHOLD:
        regime = "BULL"
    elif prev == "BULL" and ratio < REGIME_BEAR_THRESHOLD:
        regime = "BEAR"
    else:
        regime = prev
    _cache.update({"regime": regime, "ts": now})
    return regime
