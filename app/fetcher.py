import requests, time, json
from app.config import EXCLUDED_SYMBOLS, CRYPTOPANIC_TOKEN

BINANCE_BASE    = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

# Sessao com keep-alive: corta a latencia por chamada (o scan de 60 simbolos e sequencial)
_session = requests.Session()

# Candidate pool (v3: ~120 pares USDT liquidos, validados contra exchangeInfo em 2026-07).
# Evita o fetch do ticker completo (instavel no Railway). O ranking diario por volume
# seleciona os TOP_SYMBOLS_COUNT mais liquidos; pares mortos saem naturalmente do top.
_CANDIDATES = [
    "AAVEUSDT","ADAUSDT","AIGENSYNUSDT","ALGOUSDT","ALLOUSDT","APEUSDT","APTUSDT","ARBUSDT",
    "ARKMUSDT","ARPAUSDT","ARUSDT","ASTERUSDT","ATOMUSDT","AVAXUSDT","AXSUSDT","BCHUSDT",
    "BELUSDT","BNBUSDT","BONKUSDT","BTCUSDT","CAKEUSDT","CHZUSDT","COMPUSDT","CRVUSDT",
    "DASHUSDT","DOGEUSDT","DOGSUSDT","DOTUSDT","DYDXUSDT","EGLDUSDT","EIGENUSDT","ENAUSDT",
    "ENSUSDT","EPICUSDT","ETCUSDT","ETHFIUSDT","ETHUSDT","FETUSDT","FILUSDT","FLOKIUSDT",
    "FLOWUSDT","GALAUSDT","GMXUSDT","GRAMUSDT","GRTUSDT","HBARUSDT","HEIUSDT","HMSTRUSDT",
    "ICPUSDT","IDUSDT","IMXUSDT","INJUSDT","IOTAUSDT","JTOUSDT","JUPUSDT","KITEUSDT",
    "KSMUSDT","LDOUSDT","LINKUSDT","LTCUSDT","MANAUSDT","MEGAUSDT","MINAUSDT","MIRAUSDT",
    "MUBUSDT","NEARUSDT","NEOUSDT","NFPUSDT","NILUSDT","NOMUSDT","ONDOUSDT","OPUSDT",
    "ORDIUSDT","PAXGUSDT","PENDLEUSDT","PENGUUSDT","PEPEUSDT","POLUSDT","PUMPUSDT","PYTHUSDT",
    "RENDERUSDT","REUSDT","RIFUSDT","ROSEUSDT","RUNEUSDT","SANDUSDT","SEIUSDT","SENTUSDT",
    "SHIBUSDT","SLPUSDT","SNXUSDT","SOLUSDT","SPCXBUSDT","STRKUSDT","STXUSDT","SUIUSDT",
    "SUSDT","SYNUSDT","TAOUSDT","THEUSDT","TIAUSDT","TLMUSDT","TRBUSDT","TRUMPUSDT",
    "TRXUSDT","UNIUSDT","UUSDT","VETUSDT","WIFUSDT","WLDUSDT","WLFIUSDT","WUSDT",
    "XAUTUSDT","XLMUSDT","XPLUSDT","XRPUSDT","XTZUSDT","ZECUSDT","ZKPUSDT",
]

MIN_QUOTE_VOLUME_24H = 5_000_000  # piso de liquidez (slippage real em pares de cauda >> 0.1% modelado)

def _get(url, params=None, retries=3, timeout=15):
    for i in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code in (418, 429):
                print(f"[fetcher] rate limit {r.status_code}, aguardando 60s")
                time.sleep(60); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i < retries-1: time.sleep(2)
            else: print(f"[fetcher] FAIL {url}: {e}"); return None

def get_klines(symbol, interval, limit=100, drop_forming=False):
    """drop_forming=True descarta o ultimo candle (em formacao): indicadores e sinais
    passam a usar SOMENTE candles fechados (v3) - elimina flicker de cruzamento."""
    data = _get(f"{BINANCE_BASE}/api/v3/klines", {"symbol":symbol,"interval":interval,"limit":limit})
    if not data: return []
    if drop_forming and len(data) > 1:
        data = data[:-1]
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
    if not data or "lastFundingRate" not in data: return None
    try: return float(data["lastFundingRate"])
    except (TypeError, ValueError): return None

def get_top_symbols_by_volume(n=60):
    # Fetch only our candidate pool - small payload, reliable on any network
    candidates = [s for s in _CANDIDATES if s not in EXCLUDED_SYMBOLS]
    try:
        # symbols= aceita ate ~100 por chamada com folga de URL; dividimos em chunks
        tickers = []
        for i in range(0, len(candidates), 100):
            chunk = candidates[i:i+100]
            data = _get(f"{BINANCE_BASE}/api/v3/ticker/24hr",
                        {"symbols": json.dumps(chunk), "type": "MINI"}, timeout=20)
            if data: tickers += data
        if not tickers:
            print(f"[fetcher] top_symbols API failed, using candidate head ({n})")
            return candidates[:n]
        filtered = [t for t in tickers if float(t.get("quoteVolume", 0)) > MIN_QUOTE_VOLUME_24H]
        filtered.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        result = [t["symbol"] for t in filtered[:n]]
        if not result:
            return candidates[:n]
        print(f"[fetcher] top {len(result)} symbols: {result[:5]}...")
        return result
    except Exception as e:
        print(f"[fetcher] top_symbols error: {e}")
        return candidates[:n]

def get_cryptopanic_sentiment(symbol):
    if not CRYPTOPANIC_TOKEN: return None
    coin = symbol[:-4] if symbol.endswith("USDT") else symbol[:3]
    try:
        r = requests.get("https://cryptopanic.com/api/free/v1/posts/",
            params={"auth_token":CRYPTOPANIC_TOKEN,"currencies":coin,
                    "filter":"hot","public":"true"}, timeout=8)
        if r.status_code != 200: return None
        items = r.json().get("results", [])[:10]
        if not items: return "neutral"
        pos   = sum(i.get("votes",{}).get("positive",0) for i in items)
        neg   = sum(i.get("votes",{}).get("negative",0) for i in items)
        total = pos + neg
        if total == 0: return "neutral"
        if pos/total > 0.6: return "bullish"
        if neg/total > 0.6: return "bearish"
        return "neutral"
    except Exception as e:
        print(f"[fetcher] cryptopanic {coin}: {e}")
        return None
