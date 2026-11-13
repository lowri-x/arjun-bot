from __future__ import annotations
import json, logging, math, os, time
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect

IST = ZoneInfo('Asia/Kolkata')
ROOT = Path(__file__).parent

INDEXES = {
    "NIFTY 50": {"token": "99926000", "symbol": "NIFTY", "step": 50},
    "BANK NIFTY": {"token": "99926009", "symbol": "BANKNIFTY", "step": 100}
}
VIX_TOKEN = "99926017"

# 🚨 2026 ਦੀਆਂ ਛੁੱਟੀਆਂ (ਅਧਿਕਾਰਤ NSE ਸੂਚੀ ਅਨੁਸਾਰ)
HOLIDAYS = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", 
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-09", "2026-11-10", 
    "2026-11-24", "2026-12-25"
}

ENV = {k: os.getenv(k) for k in ["API_KEY", "CLIENT_ID", "PASSWORD", "TOTP_SECRET", "BOT_TOKEN", "CHAT_ID", "GIST_ID", "GIST_TOKEN"]}
MAX_RISK = float(os.getenv("MAX_RISK_PER_TRADE", "2000"))
POLL = int(os.getenv("POLL_SECONDS", "300"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("arjun")

DEFAULT_STATE = {"active": [], "history": [], "last_start_msg": "", "last_end_msg": "", "last_signal": {}}

def now():
    return datetime.now(IST)

def require_env():
    missing = [k for k, v in ENV.items() if not v]
    if missing:
        raise RuntimeError("Missing GitHub Secrets: " + ", ".join(missing))

def tg(msg):
    if not ENV["BOT_TOKEN"] or not ENV["CHAT_ID"]: return
    try:
        url = f'https://api.telegram.org/bot{ENV["BOT_TOKEN"]}/sendMessage'
        r = requests.post(url, json={"chat_id": ENV["CHAT_ID"], "text": msg, "parse_mode": "HTML"}, timeout=15)
        r.raise_for_status()
    except Exception:
        log.exception("Telegram send failed")

def headers():
    return {
        "Authorization": "Bearer " + ENV["GIST_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def validate_state(state):
    if not isinstance(state, dict) or not isinstance(state.get("history"), list):
        raise RuntimeError("Gist state invalid; refusing to reset paper trades.")
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v.copy() if isinstance(v, (list, dict)) else v)
    return state

def load_state():
    if ENV["GIST_ID"] and ENV["GIST_TOKEN"]:
        r = requests.get(f"https://api.github.com/gists/{ENV['GIST_ID']}", headers=headers(), timeout=20)
        r.raise_for_status()
        files = r.json().get("files", {})
        if "trades.json" not in files:
            raise RuntimeError("Gist missing trades.json")
        return validate_state(json.loads(files["trades.json"]["content"]))
    
    p = ROOT / "trades.json"
    if p.exists():
        return validate_state(json.loads(p.read_text()))
    return validate_state(json.loads(json.dumps(DEFAULT_STATE)))

def save_state(state):
    content = json.dumps(state, indent=2, ensure_ascii=False)
    if ENV["GIST_ID"] and ENV["GIST_TOKEN"]:
        r = requests.patch(
            f"https://api.github.com/gists/{ENV['GIST_ID']}",
            headers=headers(),
            json={"files": {"trades.json": {"content": content}}},
            timeout=20
        )
        r.raise_for_status()
    else:
        p = ROOT / "trades.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(p)

def login():
    a = SmartConnect(api_key=ENV["API_KEY"])
    res = a.generateSession(ENV["CLIENT_ID"], ENV["PASSWORD"], pyotp.TOTP(ENV["TOTP_SECRET"]).now())
    if not isinstance(res, dict) or res.get("status") is not True:
        raise RuntimeError("Angel One login failed")
    return a

def instruments():
    p = ROOT / "instruments.json"
    if not p.exists() or time.time() - p.stat().st_mtime > 20 * 3600:
        u = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        r = requests.get(u, timeout=45)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError("Invalid instrument master")
        p.write_text(json.dumps(data))
    
    df = pd.DataFrame(json.loads(p.read_text()))
    required = {"token", "symbol", "name", "expiry", "strike", "lotsize", "instrumenttype", "exch_seg"}
    if not required.issubset(df.columns):
        raise RuntimeError("Instrument master schema changed")
    return df

def candles(a, token, interval, days=5):
    end = now()
    start = end - timedelta(days=days)
    q = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": start.strftime("%Y-%m-%d %H:%M"),
        "todate": end.strftime("%Y-%m-%d %H:%M")
    }
    for n in range(3):
        try:
            time.sleep(1.2)
            x = a.getCandleData(q)
            if not isinstance(x, dict) or x.get("status") is not True or not x.get("data"):
                raise RuntimeError("SmartAPI candle response invalid/empty")
            df = pd.DataFrame(x["data"], columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            if df["timestamp"].dt.tz is None:
                df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
            else:
                df["timestamp"] = df["timestamp"].dt.tz_convert(IST)
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
            df = df[(df.high >= df.low) & (df.open > 0) & (df.close > 0)]
            return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        except Exception as e:
            error = e
            log.warning("Candle API failed: %s", e)
            time.sleep(2 * (n + 1))
    raise RuntimeError(f"Candle API failed: {error}")

def completed(df, m):
    cutoff = now() - timedelta(minutes=m)
    return df[df["timestamp"] < cutoff].copy().reset_index(drop=True)

def wilder(s, n=14):
    return s.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

def indicator(df):
    x = df.copy()
    c, h, l, o = x.close, x.high, x.low, x.open
    
    x['ema9'] = c.ewm(span=9, adjust=False).mean()
    x['ema21'] = c.ewm(span=21, adjust=False).mean()
    
    delta = c.diff()
    gain = wilder(delta.clip(lower=0))
    loss = wilder(-delta.clip(upper=0))
    rs = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    x['rsi'] = rs.where(~((loss == 0) & (gain > 0)), 100).fillna(50)
    
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    x['atr'] = wilder(tr)
    
    up, dn = h.diff(), -l.diff()
    pdm, mdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=x.index), pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=x.index)
    pdi = 100 * wilder(pdm) / x['atr'].replace(0, np.nan)
    mdi = 100 * wilder(mdm) / x['atr'].replace(0, np.nan)
    x['plus_di'], x['minus_di'] = pdi, mdi
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    x['adx'] = wilder(dx)
    
    ml = (h + l) / 2
    ub, lb = ml + 3 * x['atr'], ml - 3 * x['atr']
    fu, fl = ub.copy(), lb.copy()
    dir = pd.Series(index=x.index, dtype=int)
    
    for i in range(1, len(x)):
        if c.iloc[i] > fu.iloc[i-1]: dir.iloc[i] = 1
        elif c.iloc[i] < fl.iloc[i-1]: dir.iloc[i] = -1
        else: dir.iloc[i] = dir.iloc[i-1]
        if dir.iloc[i] == 1:
            fl.iloc[i] = max(fl.iloc[i], fl.iloc[i-1]) if dir.iloc[i-1] == 1 else fl.iloc[i]
        else:
            fu.iloc[i] = min(fu.iloc[i], fu.iloc[i-1]) if dir.iloc[i-1] == -1 else fu.iloc[i]
    x['st_dir'] = dir
    
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    uw, lw = h - np.maximum(o, c), np.minimum(o, c) - l
    pb, prb = (c.shift(1) > o.shift(1)), (c.shift(1) < o.shift(1))
    cb, crb = (c > o), (c < o)
    
    x['pat_bull_engulf'] = prb & cb & (c >= o.shift(1)) & (o <= c.shift(1)) & (body > body.shift(1))
    x['pat_bear_engulf'] = pb & crb & (c <= o.shift(1)) & (o >= c.shift(1)) & (body > body.shift(1))
    x['pat_hammer'] = (lw >= 2.0 * body) & (uw <= 0.3 * rng)
    x['pat_shooting_star'] = (uw >= 2.0 * body) & (lw <= 0.3 * rng)
    
    return x

def ltp(a, exchange, symbol, token):
    r = a.ltpData(exchange, symbol, str(token))
    if not isinstance(r, dict) or r.get("status") is not True:
        raise RuntimeError("LTP API failed")
    v = float(r["data"]["ltp"])
    if not math.isfinite(v) or v <= 0:
        raise RuntimeError("Invalid LTP")
    return v

def find_contract(master, index, strike, kind, day):
    sym = INDEXES[index]["symbol"]
    d = master[(master.name.astype(str) == sym) & (master.instrumenttype.astype(str) == 'OPTIDX') & (master.exch_seg.astype(str) == 'NFO')].copy()
    d = d[d.symbol.astype(str).str.endswith(kind)]
    
    # 🚨 EXPIRY FIX: mixed format ਅਤੇ nearest expiry
    d['expiry_dt'] = pd.to_datetime(d['expiry'], errors='coerce', format='mixed')
    d = d[d.expiry_dt.notna() & (d.expiry_dt >= pd.Timestamp(day))]
    d['strike_num'] = pd.to_numeric(d['strike'], errors='coerce')
    
    if d.empty: return None
    
    # nearest expiry sort
    d = d.sort_values("expiry_dt")
    match = d[d.strike_num == float(strike)]
    if match.empty: return None
    
    r = match.iloc[0]
    try: lot = int(float(r['lotsize']))
    except: return None
    if lot <= 0: return None
    return str(r['token']), str(r['symbol']), 'NFO', lot

def signal_for(d5, d15):
    if len(d5) < 40 or len(d15) < 40: return None
    d5 = indicator(d5)
    d15 = indicator(d15)
    
    c15 = d15.iloc[-1]
    htf_bull = (c15.close > c15.ema21) and (c15.st_dir == 1)
    htf_bear = (c15.close < c15.ema21) and (c15.st_dir == -1)
    
    c5, p5 = d5.iloc[-1], d5.iloc[-2]
    adx_ok = (c5.adx > 20) and (c5.adx > p5.adx)
    bull_candle = bool(c5.pat_bull_engulf or c5.pat_hammer or (c5.close > p5.high))
    bear_candle = bool(c5.pat_bear_engulf or c5.pat_shooting_star or (c5.close < p5.low))
    
    if htf_bull and (c5.ema9 > c5.ema21) and (52 <= c5.rsi <= 75) and adx_ok and (c5.plus_di > c5.minus_di) and bull_candle: 
        return "CE"
    if htf_bear and (c5.ema9 < c5.ema21) and (25 <= c5.rsi <= 48) and adx_ok and (c5.minus_di > c5.plus_di) and bear_candle: 
        return "PE"
    return None

def monitor(state, a):
    keep = []
    for t in state["active"]:
        try:
            v = ltp(a, t["exch"], t["symbol"], t["opt_token"])
        except Exception as e:
            log.warning("Trade monitor unavailable: %s", e)
            keep.append(t)
            continue
            
        status = "TARGET_HIT" if v >= t["target_premium"] else ("STOP_LOSS_HIT" if v <= t["sl_premium"] else None)
        if status:
            t["status"] = status
            t["exit_premium"] = v
            t["exit_time"] = now().isoformat()
            state["history"].append(t)
            emoji = "✅" if status == "TARGET_HIT" else "❌"
            tg(f"{emoji} <b>{t['name']} {t['type']} ਟ੍ਰੇਡ ਬੰਦ</b>\n{status}\nEntry: ₹{t['entry_premium']:.2f} | Exit: ₹{v:.2f}")
        else:
            keep.append(t)
    state["active"] = keep

def eod_close(state, a):
    for t in state["active"]:
        try:
            v = ltp(a, t["exch"], t["symbol"], t["opt_token"])
            t["exit_premium"] = v
            t["status"] = "EOD_CLOSED_PAPER"
            t["pnl_before_costs"] = round((v - t["entry_premium"]) * t["qty"], 2)
        except Exception as e:
            t["exit_premium"] = None
            t["status"] = "UNRESOLVED_EOD"
            t["note"] = str(e)
        t["exit_time"] = now().isoformat()
        state["history"].append(t)
        tg(f"🔴 EOD <b>{t['name']} {t['type']}</b>\n{t['status']} | Exit: ₹{t.get('exit_premium', 'N/A')}")
    state["active"] = []

def scan(a, master, state):
    monitor(state, a)
    try:
        vix = ltp(a, 'NSE', 'India VIX', VIX_TOKEN)
    except Exception as e:
        log.error('India VIX unavailable; skip new entries: %s', e)
        save_state(state)
        return
        
    for name, cfg in INDEXES.items():
        try:
            d15 = completed(candles(a, cfg['token'], 'FIFTEEN_MINUTE'), 15)
            d5 = completed(candles(a, cfg['token'], 'FIVE_MINUTE'), 5)
            if len(d5) < 40 or len(d15) < 40: continue
            
            kind = signal_for(d5, d15)
            if not kind or any(t['name'] == name for t in state['active']): continue
            
            bar = d5.iloc[-1].timestamp.isoformat()
            key = f"{name}|{kind}|{bar}"
            if state['last_signal'].get(name) == key: continue
            
            spot = float(d5.iloc[-1].close)
            step = cfg['step']
            strike = round((spot + step) / step) * step if kind == 'CE' else round((spot - step) / step) * step
            
            contract = find_contract(master, name, strike, kind, now())
            if not contract:
                log.warning("No exact option contract: %s %s %s", name, strike, kind)
                state['last_signal'][name] = key
                continue
                
            token, symbol, ex, lot = contract
            premium = ltp(a, ex, symbol, token)
            atr_ratio = float(indicator(d15).iloc[-1].atr) / max(float(d15.iloc[-1].close), 1e-9)
            
            pct = 0.30 if vix > 18 or atr_ratio > 0.015 else 0.25
            sl = premium * (1 - pct)
            target = premium * (1 + pct * 1.5)
            risk = (premium - sl) * lot
            
            if risk > MAX_RISK:
                log.info('Risk cap blocked %s: %.2f', name, risk)
                state['last_signal'][name] = key
                continue
                
            trade = {
                'name': name, 'type': kind, 'side': 'BUY', 'symbol': symbol, 'opt_token': token, 'exch': ex,
                'entry_premium': premium, 'sl_premium': sl, 'target_premium': target, 'qty': lot,
                'risk_rupees': round(risk, 2), 'sl_pct': pct, 'signal_candle': bar,
                'entry_time': now().isoformat(), 'status': 'PAPER_ACTIVE'
            }
            state['active'].append(trade)
            
            msg = f"🚀 <b>ARJUN {kind} BUY SIGNAL (PAPER)</b>\n\n"
            msg += f"📊 {name} ({spot:.2f})\n🎯 Option: <b>{symbol}</b>\n"
            msg += f"💰 Entry: ₹{premium:.2f}\n🛑 SL: ₹{sl:.2f} ({pct:.0%})\n"
            msg += f"🎯 Target: ₹{target:.2f} (1:1.5)\n"
            msg += f"📦 Qty: {lot} (1 Lot)\n💵 Risk: ₹{risk:.2f}\n"
            msg += f"📈 VIX: {vix:.2f}\n\n<i>NO LIVE ORDER PLACED.</i>"
            tg(msg)
            
            state['last_signal'][name] = key
        except Exception:
            log.exception('%s scan failed', name)
            
    save_state(state)

def run():
    require_env()
    n = now()
    day = n.strftime('%Y-%m-%d')
    
    if n.weekday() >= 5 or day in HOLIDAYS:
        log.info('Weekend/holiday; exit')
        return
        
    state = load_state()
    
    if n.time() >= dtime(15, 20):
        if state.get('last_end_msg') != day:
            eod_close(state, login())
            state['last_end_msg'] = day
            save_state(state)
            tg('🔴 ARJUN EOD paper tracking complete.')
        return
        
    # 🚨 TIMEOUT FIX: Session 1 ends at 12:25, Session 2 starts at 12:30
    if dtime(8, 52) <= n.time() < dtime(12, 25):
        end = datetime(n.year, n.month, n.day, 12, 25, tzinfo=IST)
    elif dtime(12, 30) <= n.time() < dtime(15, 17):
        end = datetime(n.year, n.month, n.day, 15, 17, tzinfo=IST)
    else:
        log.info('Outside scanner sessions')
        return
        
    a = login()
    master = instruments()
    
    if state.get('last_start_msg') != day:
        state['last_start_msg'] = day
        save_state(state)
        tg(f"✅ ARJUN scanner started {n:%H:%M} IST.\nEntries after 09:30. Paper mode.")
        
    while now() < end:
        if now().time() >= dtime(9, 30):
            scan(a, master, state)
        else:
            log.info('Waiting for 09:30 entry gate')
            
        save_state(state)
        sec = POLL - (now().minute * 60 + now().second) % POLL
        time.sleep(max(10, min(sec, max(1, int((end - now()).total_seconds())))))

if __name__ == '__main__':
    try:
        run()
    except Exception as e:
        log.exception('Fatal scanner error')
        tg(f"🚨 ARJUN scanner error: {type(e).__name__}: {e}")
        raise
