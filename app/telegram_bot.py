import asyncio,threading,requests,traceback
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
from app import database
from app.config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID,TRADING_MODE,MAX_CONCURRENT_POSITIONS

_app=None
_API=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None

MENU=("<b>TTI Finance Bot</b>\n"
      "/status  — capital, PnL, regime e posicoes\n"
      "/trades  — ultimos 5 trades\n"
      "/report  — resumo geral\n"
      "/kill    — pausa novas operacoes\n"
      "/resume  — retoma operacoes\n"
      "/ping    — testa se estou vivo\n"
      "/help    — este menu")

def _side(a):   return "🟢 LONG" if a=="BUY" else "🔴 SHORT"
def _money(x):  return f"${float(x or 0):,.2f}"
def _pct(x):    return f"{float(x or 0):+.2f}%"
def _exit_emoji(status): return "🎯" if status=="CLOSED_TP" else ("🛑" if status=="CLOSED_SL" else "⚪")

def start():
    if not TELEGRAM_BOT_TOKEN:
        print("[telegram] DISABLED - TELEGRAM_BOT_TOKEN not set"); return
    if not TELEGRAM_CHAT_ID:
        print("[telegram] WARN - TELEGRAM_CHAT_ID not set: comandos funcionam, mas notificacoes push nao")
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
        # stop_signals=None: run_polling roda numa thread secundaria e o default tenta
        # instalar signal handlers (SIGINT/SIGTERM), que so funcionam na thread principal
        # -> sem isso, o polling crashava e os comandos (/status) nunca respondiam.
        _app.run_polling(close_loop=False, stop_signals=None)
    except Exception as e:
        print(f"[telegram] FATAL ERROR: {e}")
        traceback.print_exc()

def notify(msg):
    print(f"[tg] {msg}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return  # sem token/chat_id -> so log (nao quebra o loop de trading)
    for pm in ("HTML", None):   # tenta HTML; se vier 400 (markup invalido), reenvia texto puro
        try:
            payload={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"disable_web_page_preview":True}
            if pm: payload["parse_mode"]=pm
            r=requests.post(f"{_API}/sendMessage",json=payload,timeout=8)
            if r.status_code==200: return
            if pm and r.status_code==400: continue
            print(f"[tg] sendMessage FAIL {r.status_code}: {r.text[:200]}"); return
        except Exception as e:
            print(f"[tg] sendMessage error: {e}"); return

# ---- notificacoes push (bot -> voce) ----
def notify_signal(s):
    notify(f"🔔 <b>Sinal</b> {_side(s.get('action'))} <b>{s.get('symbol','')}</b> ({s.get('timeframe','')})\n"
           f"Preco {_money(s.get('price'))} · RSI {float(s.get('rsi',0)):.0f} · "
           f"ADX {float(s.get('adx',0)):.0f} · regime {s.get('regime','?')}")

def notify_trade_opened(trade,approved,reason):
    if not approved:
        notify(f"⛔ Sinal ignorado — {reason}"); return
    notify(f"✅ <b>Trade aberto</b>  {_side(trade.get('action'))} <b>{trade.get('symbol','')}</b>\n"
           f"Entrada {_money(trade.get('entry_price'))}\n"
           f"🛑 SL {_money(trade.get('stop_loss'))}   🎯 TP {_money(trade.get('take_profit'))}")

def notify_trade_closed(t):
    pnl=float(t.get('pnl_usdt') or 0); sign="+" if pnl>=0 else ""
    head={"CLOSED_TP":"🎯 <b>Take Profit</b>","CLOSED_SL":"🛑 <b>Stop Loss</b>"}.get(t.get('status'),"⚪ <b>Fechado</b>")
    notify(f"{head}  {_side(t.get('action'))} <b>{t.get('symbol','')}</b>\n"
           f"Saida {_money(t.get('exit_price'))}\n"
           f"Resultado {sign}{_money(pnl)} ({_pct(t.get('pnl_pct'))})")

def notify_daily_summary(s):
    pnl=float(s.get('pnl_total_usdt',0)); sign="+" if pnl>=0 else ""
    notify(f"📊 <b>Resumo do dia</b>\n"
           f"💰 Capital {_money(s.get('current_capital_usdt'))}\n"
           f"📈 PnL total {sign}{_money(pnl)} ({_pct(s.get('pnl_pct_total'))})\n"
           f"🔁 Trades {s.get('total_trades',0)} · Win rate {float(s.get('win_rate',0)):.0f}%")

def notify_kill_switch(reason): notify(f"🚨 <b>KILL SWITCH</b> — {reason}")

# ---- comandos (voce -> bot) ----
async def cmd_ping(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🏓 pong")

async def cmd_start(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(MENU,parse_mode="HTML")

async def cmd_help(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(MENU,parse_mode="HTML")

async def cmd_status(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        s=database.get_portfolio_stats(); rs=database.get_risk_state()
        opens=database.get_all_open_trades()
        try:
            from app import regime_detector; regime=regime_detector.current_regime()
        except Exception: regime="?"
        pnl=float(s.get('pnl_total_usdt',0)); sign="+" if pnl>=0 else ""
        lines=["📈 <b>Status</b>",
               f"💰 Capital: {_money(s.get('current_capital_usdt'))}",
               f"📊 PnL: {sign}{_money(pnl)} ({_pct(s.get('pnl_pct_total'))})",
               f"🧭 Regime: {regime}",
               f"📌 Posicoes: {len(opens)}/{MAX_CONCURRENT_POSITIONS}"]
        for t in opens[:MAX_CONCURRENT_POSITIONS]:
            lines.append(f"   {_side(t.get('action'))} {t.get('symbol')} @ {_money(t.get('entry_price'))}")
        lines.append(f"🔁 Trades hoje: {rs.get('trades_today',0)} · {TRADING_MODE.upper()}")
        if rs.get('kill_switch_active'): lines.append("🚨 <b>KILL SWITCH ATIVO</b>")
        await u.message.reply_text("\n".join(lines),parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_trades(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        trades=database.get_trades(limit=5)
        if not trades: await u.message.reply_text("Nenhum trade ainda."); return
        lines=["🧾 <b>Ultimos 5 trades</b>"]
        for t in trades:
            pnl=float(t.get('pnl_usdt') or 0); sign="+" if pnl>=0 else ""
            st=t.get('status'); tag="aberto" if st=="OPEN" else f"{sign}{_money(pnl)}"
            lines.append(f"{_exit_emoji(st)} {_side(t.get('action'))} {t.get('symbol')} · {tag}")
        await u.message.reply_text("\n".join(lines),parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_report(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        s=database.get_portfolio_stats()
        pnl=float(s.get('pnl_total_usdt',0)); sign="+" if pnl>=0 else ""
        best=s.get('melhor_trade_usdt'); worst=s.get('pior_trade_usdt')
        lines=["🧮 <b>Relatorio geral</b>",
               f"🔁 Trades: {s.get('total_trades',0)} · Win rate {float(s.get('win_rate',0)):.0f}%",
               f"📈 PnL: {sign}{_money(pnl)} ({_pct(s.get('pnl_pct_total'))})"]
        if best is not None and worst is not None:
            lines.append(f"🏆 Melhor {_money(best)} · 💀 Pior {_money(worst)}")
        await u.message.reply_text("\n".join(lines),parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_kill(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        database.update_risk_state(kill_switch_active=True,kill_switch_reason="cmd /kill")
        await u.message.reply_text("🚨 Kill switch <b>ON</b>. Novas operacoes pausadas.",parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")

async def cmd_resume(u:Update,c:ContextTypes.DEFAULT_TYPE):
    try:
        # Retomar tambem zera o breaker de perdas consecutivas (senao o /resume nao
        # destrava o bot quando ele parou por 3 perdas seguidas).
        database.update_risk_state(kill_switch_active=False,kill_switch_reason=None,consecutive_losses=0)
        await u.message.reply_text("✅ Kill switch <b>OFF</b> + perdas consecutivas zeradas. Retomando.",parse_mode="HTML")
    except Exception as e:
        await u.message.reply_text(f"Erro: {e}")
