# -*- coding: utf-8 -*-
"""
Backtest v3 - motor de calibracao do "proximo modelo" (felipemarcon-TTI/finance).

Modela a spec v3:
 - Avaliacao SOMENTE em candle FECHADO (15m/1h/4h boundaries); MR no boundary 4h.
 - Short simetrico: trend BUY/SELL nos dois regimes (sem use_trend); direcao vem do alinhamento 4h.
 - Universo: top N (60) do pool por volume mediano diario DENTRO da janela (aprox. do re-rank diario).
 - Risco: 1.5%/trade, MAX_CONCURRENT=6, MAX/dia=8, breaker 3 perdas (reset diario),
   stop diario -5% do capital do INICIO DO DIA, cap notional 20%/posicao, gate de caixa 95%-comprometido.
 - Trailing gap fixo (fix PR#1). Custos: fee 0.1%/lado + slippage 0.1%/lado (~0.4% RT).
 - Regime BULL/BEAR por breadth EMA20>EMA50 no 4h, com histerese opcional (0.60 sobe / 0.45 desce).

Sweep mode: --sweep configs.json roda N configs reutilizando os dados carregados (segundos/config).

Uso:
  python backtest_v3.py --window 2025Q3 --cache cache_2025Q3.pkl --sweep sweep_stage1.json --out res_2025Q3.json
  Janelas: 2025Q3=2025-07-05..2025-10-05  2025Q4=2025-10-05..2026-01-05
           2026Q1=2026-01-05..2026-04-05  HOLDOUT=2026-04-05..2026-07-04
Convencoes/premissas documentadas no relatorio final.
"""
import requests, time, json, sys, os, pickle, bisect
import numpy as np
import pandas as pd

BASE="https://api.binance.com"; FUT="https://fapi.binance.com"
FETCH_SLEEP=float(os.environ.get("FETCH_SLEEP","0.12"))  # subir p/ downloads paralelos (rate limit compartilhado)
TF_MS={"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}
EMA_PAIRS=[(20,50),(10,30),(50,100),(30,80)]  # pares varridos (config "ema_pair")
WINDOWS={"2025Q3":("2025-07-05","2025-10-05"),"2025Q4":("2025-10-05","2026-01-05"),
         "2026Q1":("2026-01-05","2026-04-05"),"HOLDOUT":("2026-04-05","2026-07-04")}

# ---- fixos (nao varridos) ----
RSI_PERIOD=14; EMA_S=20; EMA_L=50; ATR_PERIOD=14; ADX_PERIOD=14
SLIPPAGE=0.001; FEE=0.001
RISK_PCT=0.015; MAX_CONC=6; MAX_DAY=8; MAX_CONSEC=3
DAILY_STOP_PCT=0.05; NOTIONAL_CAP=0.20; CASH_CAP=0.95
INITIAL_EUR=1000.0
EXCLUDED={"USDCUSDT","BUSDUSDT","TUSDUSDT","USDPUSDT","FDUSDUSDT","USDSUSDT","EURUSDT",
          "GBPUSDT","AUDUSDT","BRLUS","PAXUSDT","USD1USDT","RLUSDUSDT"}

DEFAULT_CFG={  # ponto de partida (espelha main + decisoes v3); sweep sobrescreve
    "name":"base",
    "timeframes":["4h","1h"],          # TFs de trend
    "adx_min":20.0,
    "rsi_lo":35.0,"rsi_hi":65.0,       # banda RSI do trend
    "mr_bull":[30.0,70.0],"mr_bear":[25.0,75.0],
    "sl_mult":1.5,"tp_mult":3.0,       # trend + MR BULL
    "sl_mult_bear":1.5,"tp_mult_bear":2.5,  # MR BEAR
    "funding_gate":0.0005,             # None = off
    "hysteresis":True,                 # 0.60 sobe / 0.45 desce
    "shorts":True,                     # False = so BUY (referencia)
    "trailing":"on",                   # on | off (SL/TP puros) | conservative (trail so vale no proximo candle)
    "mr_enabled":True,
    "mr_strict_align":False,           # True: MR BUY exige 4h UP / SELL exige 4h DOWN (dip em tendencia)
    "max_hold_days":None,              # int: fecha a mercado apos N dias sem SL/TP
}

def arg(name,default=None):
    if name in sys.argv:
        i=sys.argv.index(name)
        if i+1<len(sys.argv): return sys.argv[i+1]
    return default

def _get(url,params,retries=5,timeout=25):
    for i in range(retries):
        try:
            r=requests.get(url,params=params,timeout=timeout)
            if r.status_code in (418,429): time.sleep(30+10*i); continue
            r.raise_for_status(); return r.json()
        except Exception:
            if i<retries-1: time.sleep(1.5+i)
    return None

def fetch_klines(sym,interval,start_ms,end_ms):
    # limit=1000 -> weight 5 (1500 seria weight 10 e estoura 6000/min com 60+ simbolos)
    out=[]; cur=start_ms; step=TF_MS[interval]
    while cur<end_ms:
        d=_get(f"{BASE}/api/v3/klines",{"symbol":sym,"interval":interval,"startTime":cur,"endTime":end_ms,"limit":1000})
        if d is None:
            print(f"[warn] fetch truncado: {sym} {interval} em {cur}"); break
        if not d: break
        out+=d
        if len(d)<1000: break
        cur=d[-1][0]+step; time.sleep(FETCH_SLEEP)
    seen=set(); rows=[]
    for c in out:
        if c[0] in seen: continue
        seen.add(c[0])
        rows.append((c[0],float(c[1]),float(c[2]),float(c[3]),float(c[4]),float(c[5])))
    # valida cobertura (simbolo pode ter sido listado depois do inicio -> cobertura parcial legitima)
    expected=(end_ms-start_ms)//step
    if rows and expected>0:
        cov=len(rows)/expected
        if cov<0.95 and rows[0][0]<=start_ms+step:  # comecou no inicio mas faltou fim = truncado
            print(f"[warn] cobertura {sym} {interval}: {cov:.0%} ({len(rows)}/{expected})")
    return rows

def fetch_funding(sym,start_ms,end_ms):
    out=[]; cur=start_ms
    while cur<end_ms:
        d=_get(f"{FUT}/fapi/v1/fundingRate",{"symbol":sym,"startTime":cur,"endTime":end_ms,"limit":1000})
        if not d: break
        out+=d
        if len(d)<1000: break
        cur=d[-1]["fundingTime"]+1; time.sleep(FETCH_SLEEP/4)
    return sorted([(int(x["fundingTime"]),float(x["fundingRate"])) for x in out])

def indicators(rows):
    df=pd.DataFrame(rows,columns=["t","o","h","l","c","v"])
    c=df["c"]
    e20=c.ewm(span=EMA_S,adjust=False).mean(); e50=c.ewm(span=EMA_L,adjust=False).mean()
    d=c.diff(); g=d.clip(lower=0); ls=(-d).clip(lower=0)
    rs=g.ewm(alpha=1/RSI_PERIOD,adjust=False).mean()/ls.ewm(alpha=1/RSI_PERIOD,adjust=False).mean().replace(0,np.nan)
    rsi=100-100/(1+rs)
    h=df["h"]; l=df["l"]; pc=c.shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/ATR_PERIOD,adjust=False).mean()
    up=h.diff(); dn=-l.diff()
    pdm=((up>dn)&(up>0)).astype(float)*up.clip(lower=0)
    mdm=((dn>up)&(dn>0)).astype(float)*dn.clip(lower=0)
    a=1/ADX_PERIOD; st=tr.ewm(alpha=a,adjust=False).mean()
    pdi=100*pdm.ewm(alpha=a,adjust=False).mean()/st; mdi=100*mdm.ewm(alpha=a,adjust=False).mean()/st
    dx=((pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)*100).fillna(0)
    adx=dx.ewm(alpha=a,adjust=False).mean()
    return {"t":df["t"].values.astype(np.int64),"o":df["o"].values,"h":df["h"].values,
            "l":df["l"].values,"c":df["c"].values,"v":df["v"].values,
            "e20":e20.values,"e50":e50.values,"rsi":rsi.values,"atr":atr.values,"adx":adx.values}

def augment_cache_1d(cache_path,start_ms,end_ms):
    """Adiciona TF 1d a um cache existente (1 request por simbolo)."""
    universe,data,fund=pickle.load(open(cache_path,"rb"))
    warm1d=160*TF_MS["1d"]
    added=0
    for sym in universe:
        if "1d" in data[sym]: continue
        r1=fetch_klines(sym,"1d",start_ms-warm1d,end_ms)
        if len(r1)>=60:
            data[sym]["1d"]=indicators(r1); added+=1
    pickle.dump((universe,data,fund),open(cache_path,"wb"))
    print(f"[augment] 1d adicionado a {added} simbolos em {cache_path}")
    return universe,data,fund

def build_cache(pool,start_ms,end_ms,top_n,cache_path):
    warm={"15m":100*TF_MS["15m"],"1h":110*TF_MS["1h"],"4h":130*TF_MS["4h"],"1d":160*TF_MS["1d"]}
    # 1) ranking: 1h klines para volume mediano diario em quote na janela
    print(f"[data] ranking {len(pool)} simbolos por volume na janela...")
    vols={}
    h1={}
    for i,sym in enumerate(pool):
        rows=fetch_klines(sym,"1h",start_ms-warm["1h"],end_ms)
        if len(rows)<200: continue
        h1[sym]=rows
        arr=np.array([(r[0],r[4]*r[5]) for r in rows if r[0]>=start_ms])  # quote vol aprox = close*baseVol
        if len(arr)<24*30: continue  # exige >=30d de dados na janela
        days={}
        for t,qv in arr:
            d=int(t//86_400_000); days[d]=days.get(d,0)+qv
        vols[sym]=float(np.median(list(days.values())))
        if (i+1)%20==0: print(f"  rank {i+1}/{len(pool)}")
    ranked=[s for s,_ in sorted(vols.items(),key=lambda x:-x[1]) if vols[s]>=5_000_000][:top_n]
    print(f"[data] universo da janela: {len(ranked)} simbolos (piso $5M/dia mediano)")
    # 2) dados completos so para o universo
    data={}; fund={}
    for i,sym in enumerate(ranked):
        data[sym]={"1h":indicators(h1[sym])}
        r15=fetch_klines(sym,"15m",start_ms-warm["15m"],end_ms)
        r4=fetch_klines(sym,"4h",start_ms-warm["4h"],end_ms)
        if len(r15)<200 or len(r4)<60: del data[sym]; continue
        data[sym]["15m"]=indicators(r15); data[sym]["4h"]=indicators(r4)
        r1=fetch_klines(sym,"1d",start_ms-warm["1d"],end_ms)
        if len(r1)>=60: data[sym]["1d"]=indicators(r1)
        fund[sym]=fetch_funding(sym,start_ms-warm["4h"],end_ms)
        if (i+1)%10==0: print(f"  data {i+1}/{len(ranked)}")
    universe=[s for s in ranked if s in data]
    with open(cache_path,"wb") as f: pickle.dump((universe,data,fund),f)
    print(f"[data] cache salvo: {cache_path} ({len(universe)} simbolos)")
    return universe,data,fund

# ---------- pre-computo independente de config ----------
def precompute(universe,data,fund,start_ms,end_ms):
    P={"sym":{},"regime_b":None,"regime_ratio":None,"grid15":None}
    # grade aritmetica de boundaries 15m (epoch-alinhada) - independente de gaps em simbolos
    first=((start_ms//TF_MS["15m"])+1)*TF_MS["15m"]
    P["grid15"]=np.arange(first,end_ms+1,TF_MS["15m"],dtype=np.int64)
    for sym in universe:
        S={"idx15":{},"f_t":None,"f_v":None}
        d15=data[sym]["15m"]; b15=(d15["t"]+TF_MS["15m"]).astype(np.int64)
        S["b15"]=b15; S["idx15"]={int(b):i for i,b in enumerate(b15)}
        S["h15"]=d15["h"]; S["l15"]=d15["l"]; S["c15"]=d15["c"]
        d4=data[sym]["4h"]; b4=(d4["t"]+TF_MS["4h"]).astype(np.int64)
        S["b4"]=b4; S["e20_4"]=d4["e20"]; S["e50_4"]=d4["e50"]
        S["rsi4"]=d4["rsi"]; S["atr4"]=d4["atr"]; S["c4"]=d4["c"]
        arr=fund.get(sym) or []
        S["f_t"]=np.array([a[0] for a in arr],dtype=np.int64); S["f_v"]=np.array([a[1] for a in arr])
        # candidatos de trend por (par EMA, TF): cruzamentos vetorizados (filtros por config depois)
        S["trend"]={}
        for tf in ("1d","4h","1h","15m"):
            if tf not in data[sym]: continue
            dd=data[sym][tf]; b=(dd["t"]+TF_MS[tf]).astype(np.int64)
            closes=pd.Series(dd["c"])
            for pair in EMA_PAIRS:
                eS=closes.ewm(span=pair[0],adjust=False).mean().values
                eL=closes.ewm(span=pair[1],adjust=False).mean().values
                n=len(b)
                if n<pair[1]+6: S["trend"][(pair,tf)]=[]; continue
                prevS,prevL=eS[:-1],eL[:-1]; curS,curL=eS[1:],eL[1:]
                up=(prevS<=prevL)&(curS>curL); dn=(prevS>=prevL)&(curS<curL)
                idx=np.where(up|dn)[0]+1   # indice do candle do cruzamento
                ev=[]
                min_i=max(55,pair[1]+5)
                for i in idx:
                    if i<min_i or not (start_ms<=b[i]<=end_ms): continue
                    if np.isnan(dd["rsi"][i]) or np.isnan(dd["atr"][i]) or np.isnan(dd["adx"][i]) or dd["atr"][i]<=0: continue
                    ev.append((int(b[i]),"BUY" if up[i-1] else "SELL",float(dd["c"][i]),float(dd["rsi"][i]),
                               float(dd["atr"][i]),float(dd["adx"][i])))
                S["trend"][(pair,tf)]=ev
        # candidatos MR: todo boundary 4h na janela (threshold por config)
        mr=[]
        for i in range(52,len(b4)):
            if not (b4[i]>=start_ms and b4[i]<=end_ms): continue
            if np.isnan(S["rsi4"][i]) or np.isnan(S["atr4"][i]) or S["atr4"][i]<=0: continue
            mr.append((int(b4[i]),float(S["rsi4"][i]),float(S["c4"][i]),float(S["atr4"][i]),i))
        S["mr"]=mr
        P["sym"][sym]=S
    # regime ratio por boundary 4h (breadth)
    refb4=(data[universe[0]]["4h"]["t"]+TF_MS["4h"]).astype(np.int64)
    rb=[]; rv=[]
    for i,B in enumerate(refb4):
        tot=bull=0
        for sym in universe:
            S=P["sym"][sym]; j=np.searchsorted(S["b4"],B,side="right")-1
            if j<51: continue
            e20,e50=S["e20_4"][j],S["e50_4"][j]
            if np.isnan(e20) or np.isnan(e50): continue
            tot+=1; bull+= 1 if e20>e50 else 0
        if tot>0: rb.append(int(B)); rv.append(bull/tot)
    P["regime_b"]=np.array(rb,dtype=np.int64); P["regime_ratio"]=np.array(rv)
    return P

def trend4h_at(S,ts):
    j=np.searchsorted(S["b4"],ts,side="right")-1
    if j<51: return "NEUTRAL"
    e20,e50=S["e20_4"][j],S["e50_4"][j]
    if np.isnan(e20) or np.isnan(e50): return "NEUTRAL"
    return "UP" if e20>e50 else ("DOWN" if e20<e50 else "NEUTRAL")

def funding_at(S,ts):
    if len(S["f_t"])==0: return None
    j=np.searchsorted(S["f_t"],ts,side="right")-1
    return float(S["f_v"][j]) if j>=0 else None

# ---------- engine por config ----------
def run_config(cfg,universe,P,eur_rate):
    init=INITIAL_EUR*eur_rate
    # regime com/sem histerese
    ratio=P["regime_ratio"]; rb=P["regime_b"]
    reg=[]; cur="BEAR"
    for r in ratio:
        if cfg["hysteresis"]:
            if cur=="BEAR" and r>=0.60: cur="BULL"
            elif cur=="BULL" and r<0.45: cur="BEAR"
        else:
            cur="BULL" if r>=0.60 else "BEAR"
        reg.append(cur)
    def regime_at(ts):
        i=np.searchsorted(rb,ts,side="right")-1
        return reg[i] if i>=0 else "BEAR"

    # eventos de entrada por timestamp
    events={}
    PRIO={"4h_mr":0,"1d":1,"4h":2,"1h":3,"15m":4}
    ema_pair=tuple(cfg.get("ema_pair",[20,50]))
    for sym in universe:
        S=P["sym"][sym]
        for (B,rsi,close,atr,_) in (S["mr"] if cfg.get("mr_enabled",True) else []):
            rgm=regime_at(B)
            lo,hi=(cfg["mr_bull"] if rgm=="BULL" else cfg["mr_bear"])
            act="BUY" if rsi<lo else ("SELL" if rsi>hi else None)
            if not act: continue
            if not cfg["shorts"] and act=="SELL": continue
            t4=trend4h_at(S,B)
            if cfg.get("mr_strict_align"):
                if act=="BUY" and t4!="UP": continue
                if act=="SELL" and t4!="DOWN": continue
            else:
                if act=="BUY" and t4=="DOWN": continue
                if act=="SELL" and t4=="UP": continue
            f=funding_at(S,B); fg=cfg["funding_gate"]
            if f is not None and fg is not None:
                if act=="BUY" and f>fg: continue
                if act=="SELL" and f<-fg: continue
            slm,tpm=(cfg["sl_mult"],cfg["tp_mult"]) if rgm=="BULL" else (cfg["sl_mult_bear"],cfg["tp_mult_bear"])
            events.setdefault(B,[]).append((PRIO["4h_mr"],sym,"4h_mr",act,close,atr,slm,tpm,rgm))
        for tf in cfg["timeframes"]:
            for (B,act,close,rsi,atr,adx) in S["trend"].get((ema_pair,tf),[]):
                if not cfg["shorts"] and act=="SELL": continue
                if adx<cfg["adx_min"]: continue
                if not (cfg["rsi_lo"]<rsi<cfg["rsi_hi"]): continue
                if tf in ("1h","15m"):
                    t4=trend4h_at(S,B)
                    if act=="BUY" and t4=="DOWN": continue
                    if act=="SELL" and t4=="UP": continue
                f=funding_at(S,B); fg=cfg["funding_gate"]
                if f is not None and fg is not None:
                    if act=="BUY" and f>fg: continue
                    if act=="SELL" and f<-fg: continue
                rgm=regime_at(B)
                events.setdefault(B,[]).append((PRIO[tf],sym,tf,act,close,atr,cfg["sl_mult"],cfg["tp_mult"],rgm))

    # loop temporal na grade 15m
    capital=init; day_start_cap=init
    open_tr=[]; closed=[]; day=None; tday=0; consec=0; dstop=False
    peak=init; maxdd=0.0; halt_days=set()
    grid=P["grid15"]
    for B in grid:
        d=B//86_400_000
        if day!=d:
            day=d; tday=0; consec=0; dstop=False; day_start_cap=capital
        # exits
        for tr in list(open_tr):
            S=P["sym"][tr["sym"]]; i=S["idx15"].get(int(B))
            if i is None or tr["open_b"]>=B: continue
            hi,lo=S["h15"][i],S["l15"][i]
            e=tr["entry"]; atr=tr["atr"]; gap=tr["sl_dist"]; sl=tr["sl"]; tp=tr["tp"]
            mode=cfg.get("trailing","on")
            if tr["act"]=="BUY":
                fav=hi
                if mode=="on":
                    if fav>=e+2*atr: nsl=max(sl,fav-gap)
                    elif fav>=e+atr: nsl=max(sl,e)
                    else: nsl=sl
                    if nsl>sl: sl=nsl; tr["sl"]=sl
                exit_px=None; status=None
                if lo<=sl: exit_px,status=sl,"CLOSED_SL"
                elif hi>=tp: exit_px,status=tp,"CLOSED_TP"
                if mode=="conservative":
                    if fav>=e+2*atr: tr["sl"]=max(tr["sl"],fav-gap)
                    elif fav>=e+atr: tr["sl"]=max(tr["sl"],e)
            else:
                fav=lo
                if mode=="on":
                    if fav<=e-2*atr: nsl=min(sl,fav+gap)
                    elif fav<=e-atr: nsl=min(sl,e)
                    else: nsl=sl
                    if nsl<sl: sl=nsl; tr["sl"]=sl
                exit_px=None; status=None
                if hi>=sl: exit_px,status=sl,"CLOSED_SL"
                elif lo<=tp: exit_px,status=tp,"CLOSED_TP"
                if mode=="conservative":
                    if fav<=e-2*atr: tr["sl"]=min(tr["sl"],fav+gap)
                    elif fav<=e-atr: tr["sl"]=min(tr["sl"],e)
            mh=cfg.get("max_hold_days")
            if exit_px is None and mh and (B-tr["open_b"])>=mh*86_400_000:
                exit_px=float(S["c15"][i]); status="CLOSED_TIME"
            if exit_px is not None:
                qty=tr["qty"]
                fees=qty*exit_px*FEE+qty*e*FEE
                gross=(exit_px-e)*qty if tr["act"]=="BUY" else (e-exit_px)*qty
                pnl=gross-fees
                capital+=pnl; consec=0 if pnl>0 else consec+1
                tr.update({"exit":exit_px,"status":status,"pnl":pnl,"exit_b":int(B)})
                closed.append(tr); open_tr.remove(tr)
        # daily stop check (sobre capital do inicio do dia)
        if not dstop and (capital-day_start_cap) < -day_start_cap*DAILY_STOP_PCT:
            dstop=True
        # entries
        evs=events.get(int(B))
        if evs:
            evs.sort()
            for (_,sym,tf,act,close,atr,slm,tpm,rgm) in evs:
                if consec>=MAX_CONSEC: halt_days.add(int(d)); break
                if dstop: break
                if tday>=MAX_DAY: break
                if len(open_tr)>=MAX_CONC: break
                if any(t["sym"]==sym for t in open_tr): continue
                entry=close*(1+SLIPPAGE) if act=="BUY" else close*(1-SLIPPAGE)
                sl_dist=atr*slm; tp_dist=atr*tpm
                sl=entry-sl_dist if act=="BUY" else entry+sl_dist
                tp=entry+tp_dist if act=="BUY" else entry-tp_dist
                sl_pct=sl_dist/entry
                qty=(capital*RISK_PCT)/(entry*sl_pct)
                committed=sum(t["entry"]*t["qty"] for t in open_tr)
                qty=min(qty,(capital*NOTIONAL_CAP)/entry,max(0.0,capital*CASH_CAP-committed)/entry)
                if qty<=0: continue
                open_tr.append({"sym":sym,"tf":tf,"act":act,"entry":entry,"sl":sl,"tp":tp,"qty":qty,
                                "atr":atr,"sl_dist":sl_dist,"open_b":int(B),"regime":rgm,
                                "risk_eff":qty*entry*sl_pct/capital})
                tday+=1
        # equity / drawdown
        eq=capital
        for tr in open_tr:
            S=P["sym"][tr["sym"]]; i=S["idx15"].get(int(B))
            if i is None: continue
            px=S["c15"][i]
            eq+=(px-tr["entry"])*tr["qty"] if tr["act"]=="BUY" else (tr["entry"]-px)*tr["qty"]
        if eq>peak: peak=eq
        dd=(peak-eq)/peak if peak>0 else 0
        if dd>maxdd: maxdd=dd
    for tr in list(open_tr):
        S=P["sym"][tr["sym"]]; px=float(S["c15"][-1])
        qty=tr["qty"]; e=tr["entry"]
        fees=qty*px*FEE+qty*e*FEE
        gross=(px-e)*qty if tr["act"]=="BUY" else (e-px)*qty
        pnl=gross-fees; capital+=pnl
        tr.update({"exit":px,"status":"CLOSED_EOP","pnl":pnl,"exit_b":int(grid[-1])})
        closed.append(tr)
    # stats
    n=len(closed); wins=[t for t in closed if t["pnl"]>0]
    gp=sum(t["pnl"] for t in wins); gl=-sum(t["pnl"] for t in closed if t["pnl"]<=0)
    days_n=max(1,len(set(t["open_b"]//86_400_000 for t in closed)) if closed else 1)
    period_days=max(1,(int(grid[-1])-int(grid[0]))//86_400_000)
    sells=[t for t in closed if t["act"]=="SELL"]
    from collections import Counter
    return {
        "name":cfg["name"],"final_eur":round(capital/eur_rate,2),
        "return_pct":round((capital/init-1)*100,2),"trades":n,
        "trades_per_day":round(n/period_days,2),
        "win_rate":round(len(wins)/n*100,1) if n else 0.0,
        "pf":round(gp/gl,2) if gl>0 else (99.0 if gp>0 else 0.0),
        "max_dd_pct":round(maxdd*100,1),
        "expectancy_usdt":round((gp-gl)/n,3) if n else 0.0,
        "by_exit":dict(Counter(t["status"] for t in closed)),
        "by_tf":dict(Counter(t["tf"] for t in closed)),
        "by_side":{"BUY":sum(1 for t in closed if t["act"]=="BUY"),"SELL":len(sells)},
        "sell_pnl":round(sum(t["pnl"] for t in sells),2),
        "by_regime":dict(Counter(t["regime"] for t in closed)),
        "tp_exits":sum(1 for t in closed if t["status"]=="CLOSED_TP"),
        "halt_days":len(halt_days),
        "avg_risk_eff_pct":round(100*np.mean([t["risk_eff"] for t in closed]),2) if closed else 0.0,
    }

def main():
    wname=arg("--window");
    if wname and wname in WINDOWS:
        s,e=WINDOWS[wname]
    else:
        s,e=arg("--start"),arg("--end"); wname=f"{s}..{e}"
    start_ms=int(pd.Timestamp(s,tz="UTC").timestamp()*1000)
    end_ms=int(pd.Timestamp(e,tz="UTC").timestamp()*1000)
    cache=arg("--cache",f"cache_{wname}.pkl")
    top_n=int(arg("--top","60"))
    pool=json.load(open(arg("--pool","pool_v3.json")))
    er=_get(f"{BASE}/api/v3/ticker/price",{"symbol":"EURUSDT"})
    eur_rate=float(er["price"]) if er else 1.14

    if os.path.exists(cache):
        print(f"[data] cache {cache}")
        if "--augment" in sys.argv:
            universe,data,fund=augment_cache_1d(cache,start_ms,end_ms)
        else:
            universe,data,fund=pickle.load(open(cache,"rb"))
    else:
        universe,data,fund=build_cache(pool,start_ms,end_ms,top_n,cache)
    print(f"[{wname}] universo={len(universe)} | precomputando...")
    t0=time.time()
    P=precompute(universe,data,fund,start_ms,end_ms)
    print(f"[precompute] {time.time()-t0:.1f}s | grid15={len(P['grid15'])}")

    sweep=arg("--sweep")
    cfgs=[]
    if sweep:
        for c in json.load(open(sweep)):
            m=dict(DEFAULT_CFG); m.update(c); cfgs.append(m)
    else:
        cfgs=[dict(DEFAULT_CFG)]
    results=[]
    for i,cfg in enumerate(cfgs):
        t0=time.time()
        r=run_config(cfg,universe,P,eur_rate)
        r["window"]=wname; r["cfg"]={k:v for k,v in cfg.items() if k!="name"}
        results.append(r)
        print(f"  [{i+1}/{len(cfgs)}] {cfg['name']}: ret {r['return_pct']:+.2f}% | {r['trades']} tr ({r['trades_per_day']}/d) | WR {r['win_rate']}% | PF {r['pf']} | DD {r['max_dd_pct']}% | TP {r['tp_exits']} | SELL {r['by_side']['SELL']} ({time.time()-t0:.1f}s)")
    out=arg("--out",f"res_{wname}.json")
    json.dump(results,open(out,"w"),indent=1)
    print(f"[out] {out}")

if __name__=="__main__":
    main()
