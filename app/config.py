from dotenv import load_dotenv
import os
load_dotenv()

TRADING_MODE         = os.getenv("TRADING_MODE","simulation")
DATABASE_URL         = os.getenv("DATABASE_URL","")
INITIAL_CAPITAL_EUR  = float(os.getenv("INITIAL_CAPITAL_EUR","1000"))
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY","")
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID","")
CRYPTOPANIC_TOKEN    = os.getenv("CRYPTOPANIC_TOKEN","")

SYMBOLS_OVERRIDE    = os.getenv("SYMBOLS","")
TOP_SYMBOLS_COUNT   = int(os.getenv("TOP_SYMBOLS_COUNT","20"))
USE_AI_FILTER       = os.getenv("USE_AI_FILTER","false").lower() == "true"
EXCLUDED_SYMBOLS    = {"USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT","USD1USDT",
                       "EURUSDT","GBPUSDT","DAIUSDT","PAXUSDT","USDPUSDT","USDTUSDT"}

TIMEFRAMES               = ["4h","1h","15m"]
RISK_PER_TRADE_PCT       = 0.01
SLIPPAGE_PCT             = 0.001
FEE_PCT                  = 0.001
MAX_TRADES_PER_DAY       = 5
MAX_CONCURRENT_POSITIONS = 3
MAX_CONSECUTIVE_LOSSES   = 3
DEFAULT_SL_PCT           = 0.015
DEFAULT_TP_PCT           = 0.030
ATR_PERIOD               = 14
ATR_SL_MULTIPLIER        = 1.5
ATR_TP_MULTIPLIER        = 3.0
VOLUME_FILTER_MULTIPLIER = 1.2
FUNDING_RATE_MAX_BUY     = 0.0001
FUNDING_RATE_MIN_SELL    = -0.0001
RSI_PERIOD               = 14
EMA_SHORT                = 20
EMA_LONG                 = 50
RSI_OVERBOUGHT           = 65
RSI_OVERSOLD             = 35
LOOP_INTERVAL_SECONDS    = 60
MONITOR_INTERVAL_SECONDS = 30
