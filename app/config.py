import os
from dotenv import load_dotenv
load_dotenv()

TRADING_MODE          = os.getenv("TRADING_MODE", "simulation")
DATABASE_URL          = os.getenv("DATABASE_URL", "")
INITIAL_CAPITAL_EUR   = float(os.getenv("INITIAL_CAPITAL_EUR", "1000"))
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID", "")
CRYPTOPANIC_TOKEN     = os.getenv("CRYPTOPANIC_TOKEN", "")
SYMBOLS_OVERRIDE      = os.getenv("SYMBOLS", "")
TOP_SYMBOLS_COUNT     = int(os.getenv("TOP_SYMBOLS_COUNT", "60"))
USE_AI_FILTER         = os.getenv("USE_AI_FILTER", "false").lower() == "true"

EXCLUDED_SYMBOLS = {
    "USDCUSDT","BUSDUSDT","TUSDUSDT","USDPUSDT","FDUSDUSDT",
    "USDSUSDT","EURUSDT","GBPUSDT","AUDUSDT","BRLUS","PAXUSDT",
    "USD1USDT","RLUSDUSDT",
}

# ---- v3: config DEFENSIVA (backtest 5 janelas 2025-2026, ver scripts/backtest.py) ----
# Escolhida por criterio MAXIMIN (pior janela = -0.3%; 4/5 janelas positivas; holdout +0.1%).
# IMPORTANTE: a variante "agressiva" (2-4 trades/dia) foi FALSIFICADA no holdout (-32%);
# esta config prioriza nao quebrar. Expectativa honesta: ~0 a +2%/trimestre, ~0.6 trades/dia.
# Setup unico: trend-following por cruzamento de EMAs LENTAS (50x100) no 4h, long E short,
# candle FECHADO, SL/TP largos (2.5/5.0 ATR), SEM trailing, SEM mean-reversion.
TIMEFRAMES             = ["4h"]
RISK_PER_TRADE_PCT     = 0.015
SLIPPAGE_PCT           = 0.001
FEE_PCT                = 0.001
MAX_TRADES_PER_DAY     = 8
MAX_CONCURRENT_POSITIONS = 6
MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_SL_PCT         = 0.015
DEFAULT_TP_PCT         = 0.030

# Caps de exposicao (v3): elimina alavancagem oculta do sizing antigo
MAX_POSITION_NOTIONAL_PCT = 0.20   # notional por posicao <= 20% do capital
CASH_USAGE_CAP            = 0.95   # notional total <= 95% do capital (sem alavancagem)
DAILY_STOP_PCT            = 0.05   # perda diaria max sobre capital do INICIO do dia

ATR_PERIOD             = 14
ATR_SL_MULTIPLIER      = 2.5
ATR_TP_MULTIPLIER      = 5.0
# Trailing stop DESATIVADO (v3): no backtest, o trailing/breakeven convertia winners em
# scratch-losses; SL/TP largos e fixos foram mais robustos em todas as janelas.
TRAILING_ENABLED       = False

ADX_PERIOD             = 14
ADX_MIN_TREND          = 20
# Funding: +-0.0001 era igual ao funding BASE da Binance e bloqueava a maioria dos BUYs.
FUNDING_RATE_MAX_BUY   = 0.0005
FUNDING_RATE_MIN_SELL  = -0.0005

RSI_PERIOD             = 14
EMA_SHORT              = 50
EMA_LONG               = 100
RSI_OVERBOUGHT         = 65
RSI_OVERSOLD           = 35

# v3: o loop dorme MONITOR_INTERVAL_SECONDS (30s); sinais disparam por boundary de candle
# fechado (nao mais por polling de LOOP_INTERVAL_SECONDS).
MONITOR_INTERVAL_SECONDS  = 30
CANDLE_CLOSE_GRACE_SECONDS = 10   # espera pos-boundary p/ Binance consolidar o candle
HEARTBEAT_EVERY_TICKS      = 20   # ~10 min com tick de 30s

# Mean-reversion 4h: DESATIVADO por padrao (backtest 2025-2026: PF<1 em todas as janelas).
# Codigo mantido; reativavel via env USE_MEAN_REVERSION=true apos nova calibracao.
USE_MEAN_REVERSION = os.getenv("USE_MEAN_REVERSION", "false").lower() == "true"

# Presets por regime: nao desligam mais nenhum lado do book (trend roda em BULL e BEAR;
# short e a principal fonte de PnL em BEAR e tambem lucra em BULL via alts fracos).
STRATEGY_PRESETS = {
    "BULL": {
        "mr_rsi_os":  30, "mr_rsi_ob":  70,
        "sl_mult": 2.5,   "tp_mult": 5.0,
    },
    "BEAR": {
        "mr_rsi_os":  25, "mr_rsi_ob":  75,
        "sl_mult": 2.5,   "tp_mult": 5.0,
    },
}
# Histerese anti flip-flop: sobe p/ BULL em >=0.60, so volta p/ BEAR em <0.45
REGIME_BULL_THRESHOLD = 0.60
REGIME_BEAR_THRESHOLD = 0.45
