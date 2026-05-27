import requests, time
from app.config import EXCLUDED_SYMBOLS, CRYPTOPANIC_TOKEN

BINANCE_BASE    = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def _get(url, params=None, retries=3, timeout=10):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i < retries-1: time.sleep(2)
            else: print(f"[fetcher] FAIL {url}: {e}"); return None

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
    # Use type=MINI for smaller payload and longer timeout for large response
    try:
        data = _get(f"{BINANCE_BASE}/api/v3/ticker/24hr", {"type":"MINI"}, timeout=30)
        if not data:
            print("[fetcher] top_symbols: API returned None, using fallback")
            return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]
        usdt = [t for t in data if t["symbol"].endswith("USDT")
                and t["symbol"] not in EXCLUDED_SYMBOLS
                and float(t["quoteVolume"]) > 10_000_000]
        usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        result = [t["symbol"] for t in usdt[:n]]
        print(f"[fetcher] top {n} symbols loaded: {result[:5]}...")
        return result
    except Exception as e:
        print(f"[fetcher] top_symbols error: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]

def get_cryptopanic_sentiment(symbol):
    if not CRYPTOPANIC_TOKEN: return None
    coin = symbol[:-4] if symbol.endswith("USDT") else symbol[:3]
    try:
        url = "https://cryptopanic.com/api/free/v1/posts/"
        r = requests.get(url, params={"auth_token":CRYPTOPANIC_TOKEN,
            "currencies":coin,"filter":"hot","public":"true"}, timeout=8)
        if r.status_code != 200: return None
        items = r.json().get("results",[])[:10]
        if not items: return "neutral"
        pos = sum(i.get("votes",{}).get("positive",0) for i in items)
        neg = sum(i.get("votes",{}).get("negative",0) for i in items)
        total = pos + neg
        if total == 0: return "neutral"
        if pos/total > 0.6: return "bullish"
        if neg/total > 0.6: return "bearish"
        return "neutral"
    except Exception as e:
        print(f"[fetcher] cryptopanic {coin}: {e}")
        return None