import requests, time
from app.config import EXCLUDED_SYMBOLS

BINANCE_BASE    = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def _get(url, params=None, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i < retries-1: time.sleep(2)
            else: print(f"[fetcher] error {url}: {e}"); return None

def get_klines(symbol, interval, limit=100):
    data = _get(f"{BINANCE_BASE}/api/v3/klines", {"symbol":symbol,"interval":interval,"limit":limit})
    if not data: return []
    return [{"open_time":c[0],"open":float(c[1]),"high":float(c[2]),
             "low":float(c[3]),"close":float(c[4]),"volume":float(c[5])} for c in data]

def get_current_price(symbol):
    data = _get(f"{BINANCE_BASE}/api/v3/ticker/price", {"symbol":symbol})
    return float(data["price"]) if data else None

def get_eur_usdt_rate():
    data = _get(f"{BINANCE_BASE}/api/v3/ticker/price", {"symbol":"EURUSDT"})
    return float(data["price"]) if data else None

def get_funding_rate(symbol):
    data = _get(f"{BINANCE_FUTURES}/fapi/v1/premiumIndex", {"symbol":symbol})
    return float(data["lastFundingRate"]) if data else None

def get_top_symbols_by_volume(n=20):
    try:
        data = _get(f"{BINANCE_BASE}/api/v3/ticker/24hr")
        if not data: return ["BTCUSDT","ETHUSDT","BNBUSDT"]
        usdt = [t for t in data if t["symbol"].endswith("USDT")
                and t["symbol"] not in EXCLUDED_SYMBOLS
                and float(t["quoteVolume"]) > 10_000_000]
        usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        result = [t["symbol"] for t in usdt[:n]]
        print(f"[fetcher] top {n} symbols: {result}")
        return result
    except Exception as e:
        print(f"[fetcher] get_top_symbols error: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT"]
