import asyncio,threading,requests,traceback
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
from app import database
from app.config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID,TRADING_MODE

_app=None
_API=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None

def start():
    if not TELEGRAM_BOT_TOKEN:
        print("[telegram] DISABLED - TELEGRAM_BOT_TOKEN not set"); return
    if not TELEGRAM_CHAT_ID:
        print("[telegram] WARN - TELEGRAM_CHAT_ID not set: comandos funcionam, mas notificacoes push nao")
    # self-test do token no boot (aparece nos logs do Railway)
    try:
        me=requests.get(f"{_API}/getMe",timeout=8).json()
        if me.get("ok"): print(f"[telegram] token OK: @{me['result'].get('username')}")
        else: print(f"[telegram] token INVALIDO: {me}")
    except Exception as e:
        print(f"[telegram] getMe error: {e}")
    print("[telegram] starting polling thread")
    threading.Thread(target=_run,daemon=True).start()

def _run():
    global _app
    try:
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        _app=ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        for name,fn in [("ping",cmd_ping),("start",cmd_start),("status",cmd_status),
                        ("trades",cmd_trades),("report",cmd_report),
                        ("kill",cmd_kill),("resume",cmd_resume),("help",cmd_help)]:
            _app.add_handler(CommandHandler(name,fn))
        print("[telegram] polling started")
        _app.run_polling(close_loop=False)
    except Exception as e:
        print(f"[telegram] FATAL ERROR: {e}")
        traceback.print_exc()

def notify(msg):
    print(f"[tg] {msg}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return  # sem token/chat_id -> so log (nao quebra o loop de trading)
    try:
        r=requests.post(f"{_API}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"disable_web_page_preview":True},
            timeout=8)
        if r.status_code!=200:
            print(f"[tg] sendMessage FAIL {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[tg] sendMessage error: {e}")

def notify_signal(s): notify(f"Sinal {s.get('action')} {s.get('timeframe')} ${s.get('price',0):.2f} RSI:{s.get('rsi',0):.1f}")
def notify_trade_opened(trade,approved,reason):
    if approved: notify(f"Trade aberto | ${float(trade.get('entry_price',0)):.2f} SL:${float(trade.get('stop_loss',0)):.2f} TP:${float(trade.get('take_profit',0)):.2f}")
    else: notify(f"Rejeitado: {reason}")
def notify_trade_closed(t):
    pnl=float(t.get('pnl_usdt') or 0); ep=float(t.get('exit_price') or 0)
    if t.get('status')=="CLOSED_TP": notify(f"Take Profit! ${ep:.2f} +${pnl:.2f} USDT")
    else: notify(f"Stop Loss ${ep:.2f} ${pnl:.2f} USDT")
def notify_daily_summary(s): notify(f"Resumo | PnL:${float(s.get('pnl_total_usdt',0)):.2f} Win:{float(s.get('win_rate',0)):.1f}% Trades:{s.get('total_trades',0)}")
def notify_kill_switch(reason): notify(f"KILL SWITCH {reason}")

async def cmd_ping(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("pong")

async def cmd_start(u:Update,c:ContextTypes.DEFAULT_TYPE):
    nl="\n"
    msg=("TTI Finance Bot ativo!"+nl+nl+
         "/status  - Capital e posicao atual"+nl+
         "/trades  - Ultimos 5 trades"+nl+
         "/report  - Relatorio geral"+nl+
         "/kill    - Para operacoes"+nl+
         "/resume  - Retoma operacoes"+nl+
         "/help    - Esta mensagem")
    await u.message.reply_text(msg)

async def cmd_status(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        s=database.get_portfolio_stats(); rs=database.get_risk_state(); t=database.get_open_trade()
        nl="\n"
        pos=f"${float(t.get('entry_price',0)):.2f} ({t.get('action')})" if t else "Nenhuma"
        msg=(f"<b>Status</b>"+nl+
             f"Capital:${float(s.get('current_capital_usdt',0)):.2f} USDT"+nl+
             f"PnL:${float(s.get('pnl_total_usdt',0)):.2f} ({float(s.get('pnl_pct_total',0)):.2f}%)"+nl+
             f"Posicao:{pos}"+nl+f"Trades hoje:{rs.get('trades_today',0)} | {TRADING_MODE.upper()}")
        await u.message.reply_text(msg,parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_trades(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        trades=database.get_trades(limit=5)
        if not trades: await u.message.reply_text("Nenhum trade."); return
        nl="\n"
        lines=["<b>Ultimos 5 trades:</b>"]
        for t in trades:
            pnl=float(t.get('pnl_usdt') or 0)
            lines.append(f"- {t.get('action')} {t.get('timeframe')} | {t.get('status')} | {'+' if pnl>=0 else ''}${pnl:.2f}")
        await u.message.reply_text(nl.join(lines),parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_report(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        s=database.get_portfolio_stats()
        nl="\n"
        msg=(f"<b>Relatorio</b>"+nl+
             f"Trades:{s.get('total_trades',0)} Win:{float(s.get('win_rate',0)):.1f}%"+nl+
             f"PnL:${float(s.get('pnl_total_usdt',0)):.2f} USDT")
        await u.message.reply_text(msg,parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_kill(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        database.update_risk_state(kill_switch_active=True,kill_switch_reason="cmd /kill")
        await u.message.reply_text("Kill switch ON. Novas operacoes pausadas.")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_resume(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        # Retomar tambem zera o breaker de perdas consecutivas (senao o /resume nao
        # destrava o bot quando ele parou por 3 perdas seguidas).
        database.update_risk_state(kill_switch_active=False,kill_switch_reason=None,consecutive_losses=0)
        await u.message.reply_text("Kill switch OFF + perdas consecutivas zeradas. Bot retomando operacoes.")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_help(u:Update,c:ContextTypes.DEFAULT_TYPE):
    nl="\n"
    await u.message.reply_text("<b>Comandos:</b>"+nl+"/ping /start /status /trades /report /kill /resume /help",parse_mode="HTML")
