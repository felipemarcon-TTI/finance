# Trading Simulator — TTI Finance

Bot de simulacao de trading com Python 3.11, PostgreSQL e Telegram. Deploy 100% via Railway.

## Variaveis de ambiente

| Variavel | Obrigatoria |
|---|---|
| DATABASE_URL | Sim (gerado pelo Railway) |
| TELEGRAM_BOT_TOKEN | Sim |
| TELEGRAM_CHAT_ID | Sim |
| TRADING_MODE | Sim (simulation \| live) |
| SYMBOL | Sim (ex: BTCUSDT) |
| INITIAL_CAPITAL_EUR | Sim |
| ANTHROPIC_API_KEY | Nao (Fase 2) |

## Deploy Railway
1. railway.app → New Project → Deploy from GitHub
2. Repo: felipemarcon-TTI/finance
3. Add Service → Database → PostgreSQL (DATABASE_URL automatico)
4. Configure variaveis em Variables
5. Auto-deploy a cada push em main

## Telegram
/status /trades /report /kill /resume /help

## Estrategia
EMA20 x EMA50 com filtro RSI(14) | TFs: 4h 1h 15m | Risco 1% SL 1.5% TP 3%
