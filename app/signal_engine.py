from app import fetcher, indicators, database
from app.config import TIMEFRAMES, RSI_OVERBOUGHT, RSI_OVERSOLD

def detect_signal(symbol, timeframe):
    candles = fetcher.get_klines(symbol, timeframe)
    if not candles or len(candles) < 60: return None
    ind = indicators.calculate_all(candles)
    ema20,ema50,prev20,prev50,rsi,price = (ind["ema20"],ind["ema50"],ind["prev_ema20"],
                                            ind["prev_ema50"],ind["rsi"],ind["current_price"])
    action = None
    if prev20<=prev50 and ema20>ema50 and RSI_OVERSOLD<rsi<RSI_OVERBOUGHT: action="BUY"
    elif prev20>=prev50 and ema20<ema50 and RSI_OVERSOLD<rsi<RSI_OVERBOUGHT: action="SELL"
    if not action: return None
    database.save_signal(symbol,timeframe,action,price,rsi,ema20,ema50)
    return {"action":action,"symbol":symbol,"timeframe":timeframe,
            "price":price,"rsi":rsi,"ema20":ema20,"ema50":ema50}

def check_all_timeframes(symbol):
    return {tf: detect_signal(symbol, tf) for tf in TIMEFRAMES}
