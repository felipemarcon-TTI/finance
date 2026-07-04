# Trading Simulator — TTI Finance

Bot de simulacao de trading com Python 3.11, PostgreSQL e Telegram. Deploy 100% via Railway.

## Variaveis de ambiente

| Variavel | Obrigatoria |
|---|---|
| DATABASE_URL | Sim (gerado pelo Railway) |
| TELEGRAM_BOT_TOKEN | Sim |
| TELEGRAM_CHAT_ID | Sim |
| TRADING_MODE | Sim (simulation \| live) |
| INITIAL_CAPITAL_EUR | Sim |
| SYMBOLS | Nao (override do universo, ex: BTCUSDT,ETHUSDT) |
| TOP_SYMBOLS_COUNT | Nao (default 60) |
| USE_MEAN_REVERSION | Nao (default false) |
| ANTHROPIC_API_KEY | Nao (filtro IA, desligado) |

## Deploy Railway
1. railway.app → New Project → Deploy from GitHub
2. Repo: felipemarcon-TTI/finance
3. Add Service → Database → PostgreSQL (DATABASE_URL automatico)
4. Configure variaveis em Variables
5. Auto-deploy a cada push em main

## Telegram
/status /trades /report /kill /resume /help

## Estrategia (v3 — config DEFENSIVA)
- **Setup**: cruzamento EMA50 x EMA100 no 4h (long e short), RSI 35-65, ADX >= 20,
  filtro de funding ±0.05%. Avaliacao **somente em candle fechado** (boundary de 4h).
- **Saidas**: SL 1.5 ATR / TP 3.0 ATR fixos, **sem trailing**. Monitor de posicoes a cada 30s.
- **Risco**: 1.5%/trade, max 6 posicoes, 8 trades/dia, notional max 20%/posicao e 95% total
  (sem alavancagem), stop diario -5% sobre o capital do inicio do dia, breaker de 3 perdas
  consecutivas com reset diario.
- **Universo**: top 60 por volume 24h de um pool curado de ~120 pares USDT (piso $5M/dia).
- **Regime**: BULL/BEAR por breadth (EMA20>EMA50 em 4h) com histerese 0.60/0.45.
- **Short**: sintetico sobre precos spot (paper). Live exigiria conta de futuros.

### Por que esta config (validacao honesta)
Backtest fiel (2025-2026), 70+ configs, holdout intocado (`scripts/backtest.py`).
A variante "agressiva" (MR) foi **falsificada** no holdout (-32%) e perde no ano (-16%).
Esta config foi escolhida por **menor drawdown** no teste de 1 ano continuo:
+28% no ano (compounding) com maxDD 13%, ~0.75 trades/dia. Os **shorts sao o motor**
do resultado (sem short: -13% no ano). Ressalva honesta: boa parte do +28% e in-sample;
no holdout isolado deu ~-1.9%/trimestre. E um **forward-test em paper**, nao lucro validado.

### Backtest / calibracao
```
cd scripts
python backtest.py --window HOLDOUT --cache cache_HOLDOUT.pkl              # config unica
python backtest.py --window 2025Q4 --cache c.pkl --sweep sweep.json        # varredura
```
Janelas nomeadas: 2025Q3, 2025Q4, 2026Q1, HOLDOUT (ou --start/--end YYYY-MM-DD).
