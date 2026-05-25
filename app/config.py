import os
from dotenv import load_dotenv

load_dotenv()

TRADING_MODE         = os.getenv("TRADING_MODE", "simulation")
SYMBOL               = os.getenv("SYMBOL", "BTCUSDT")
DATABASE_URL         = os.getenv("DATABASE_URL")
INITIAL_CAPITAL_EUR  = float(os.getenv("INITIAL_CAPITAL_EUR", "1000"))
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID", "")
CRYPTOPANIC_TOKEN    = os.getenv("CRYPTOPANIC_TOKEN", "")

TIMEFRAMES             = ["4h", "1h", "15m"]
RISK_PER_TRADE_PCT     = 0.01
SLIPPAGE_PCT           = 0.001
FEE_PCT                = 0.001
MAX_TRADES_PER_DAY     = 5
MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_SL_PCT         = 0.015
DEFAULT_TP_PCT         = 0.030
RSI_PERIOD             = 14
EMA_SHORT              = 20
EMA_LONG               = 50
RSI_OVERBOUGHT         = 65
RSI_OVERSOLD           = 35
LOOP_INTERVAL_SECONDS  = 60
MONITOR_INTERVAL_SECONDS = 30
