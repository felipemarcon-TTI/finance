import time
import requests
from app.config import SYMBOL

BINANCE_BASE    = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1: time.sleep(2)
            else: print(f"[fetcher] Failed: {url} — {e}"); return None

def get_klines(symbol, interval, limit=100):
    data = _get(f"{BINANCE_BASE}/api/v3/klines", {"symbol":symbol,"interval":interval,"limit":limit})
    if not data: return []
    return [{"open_time":int(k[0]),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),
              "close":float(k[4]),"volume":float(k[5]),"close_time":int(k[6])} for k in data]

def get_current_price(symbol):
    data = _get(f"{BINANCE_BASE}/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"]) if data else None

def get_eur_usdt_rate():
    return get_current_price("EURUSDT")

def get_funding_rate(symbol="BTCUSDT"):
    data = _get(f"{BINANCE_FUTURES}/fapi/v1/fundingRate", {"symbol":symbol,"limit":1})
    return float(data[0]["fundingRate"]) if data else None
