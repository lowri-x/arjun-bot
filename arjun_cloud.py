import urllib.request
import json
import ssl
import os
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from SmartApi import SmartConnect
import pyotp

# ==================== ਕ੍ਰੈਡੈਂਸ਼ੀਅਲਜ਼ ====================
API_KEY = os.environ.get("API_KEY")
CLIENT_ID = os.environ.get("CLIENT_ID")
PASSWORD = os.environ.get("PASSWORD")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

INDEX_TOKENS = {
    "NIFTY 50": {"symbol": "NIFTY", "exch": "NFO", "yahoo": "^NSEI", "step": 50},
    "BANK NIFTY": {"symbol": "BANKNIFTY", "exch": "NFO", "yahoo": "^NSEBANK", "step": 100},
    "SENSEX": {"symbol": "SENSEX", "exch": "BFO", "yahoo": "^BSESN", "step": 100} 
}

MAX_RISK_PER_TRADE = 50  # ₹50 ਪ੍ਰਤੀ ਟ੍ਰੇਡ

def get_ist_time():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def is_market_open():
    now = get_ist_time()
    if now.weekday() >= 5: return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 15): return False
    if now.hour > 15 or (now.hour == 15 and now.minute > 30): return False
    return True

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try: urllib.request.urlopen(req, context=ctx, timeout=10)
    except: pass

# ==================== GIST ਹੈਂਡਲਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200: return json.loads(res.json()['files']['trades.json']['content'])
    except: pass
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except: pass

# ==================== ਡੇਟਾ & ਇੰਡੀਕੇਟਰ ====================
def fetch_data(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            res = json.loads(resp.read().decode('utf-8'))['chart']['result'][0]
            q = res['indicators']['quote'][0]
            df = pd.DataFrame({'high': q['high'], 'low': q['low'], 'close': q['close'], 'vol': q['volume']}).dropna()
            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (df['tp'] * df['vol']).cumsum() / df['vol'].cumsum()
            return df
    except: return None

def calc_ema(p, n):
    if len(p) < n: return 0
    k = 2/(n+1); e = sum(p[:n])/n
    for x in p[n:]: e = x*k + e*(1-k)
    return e

def calc_rsi(p, n=14):
    if len(p) < n+1: return 50
    g, l = [], []
    for i in range(1, len(p)):
        d = p[i]-p[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag, al = sum(g[:n])/n, sum(l[:n])/n
    for i in range(n, len(g)):
        ag = (ag*(n-1)+g[i])/n; al = (al*(n-1)+l[i])/n
    return 100 - (100/(1+(ag/al))) if al>0 else 100

def calc_adx(h, l, c, n=14):
    if len(c) < n+1: return 0
    pdm, mdm, trs = [], [], []
    for i in range(1, len(c)):
        up, dn = h[i]-h[i-1], l[i-1]-l[i]
        pdm.append(up if up>dn and up>0 else 0); mdm.append(dn if dn>up and dn>0 else 0)
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    ap, am, at = sum(pdm[-n:])/n, sum(mdm[-n:])/n, sum(trs[-n:])/n
    if at == 0: return 0
    pdi, mdi = (ap/at)*100, (am/at)*100
    return abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0

def find_option(idx, strike, typ, df):
    sym, exch = INDEX_TOKENS[idx]["symbol"], INDEX_TOKENS[idx]["exch"]
    tgt = float(strike)*100
    opts = df[(df['name']==sym) & (df['instrumenttype']=='OPTIDX') & (df['exch_seg']==exch)].copy()
    if opts.empty: return None, None, None
    opts['s_float'] = pd.to_numeric(opts['strike'], errors='coerce')
    m = opts[opts['s_float'] == tgt]
    if m.empty:
        avail = opts['s_float'].dropna().unique()
        if len(avail)==0: return None, None, None
        m = opts[opts['s_float'] == min(avail, key=lambda x: abs(x-tgt))]
    m = m[m['symbol'].str.endswith(typ)]
    if m.empty: return None, None, None
    return m.iloc[0]['token'], m.iloc[0]['symbol'], exch

def get_ltp(angel, tok, exch):
    try:
        d = angel.ltpData(exch, "", tok)
        if d['status']: return d['data']['ltp']
    except: return 0

# ==================== ਮੁੱਖ ਲਾਜਿਕ ====================
def check_trades(trades, angel):
    rem = []
    for t in trades["active"]:
        cur = get_ltp(angel, t["opt_token"], t["exch"])
        if cur == 0: rem.append(t); continue
        
        status = None; exit_p = cur
        is_ce = t["type"] == "CE"
        
        if (is_ce and cur <= t["sl"]) or (not is_ce and cur >= t["sl"]):
            status = "STOP_LOSS_HIT ❌"
            exit_p = t["sl"]
        elif t["status"] == "ACTIVE":
            if (is_ce and cur >= t["t1"]) or (not is_ce and cur <= t["t1"]):
                t["status"] = "T1_HIT"
                t["sl"] = t["entry"] # SL ਐਂਟਰੀ 'ਤੇ
                send_telegram(f"✅ <b>{t['name']} T1 ਹਿੱਟ!</b>\nਅੱਧਾ ਪ੍ਰੋਫਿਟ ਬੁੱਕ ਕਰੋ। SL ਐਂਟਰੀ (₹{t['entry']:.2f}) 'ਤੇ ਲੈ ਆਓ।\nT2: ₹{t['t2']:.2f}")
        elif t["status"] == "T1_HIT":
            if (is_ce and cur >= t["t2"]) or (not is_ce and cur <= t["t2"]):
                status = "TARGET_2_HIT ✅"
                exit_p = t["t2"]
                
        if status:
            t["status"] = status; t["exit"] = exit_p; trades["history"].append(t)
            send_telegram(f"🏁 <b>{t['name']} ਟ੍ਰੇਡ ਬੰਦ!</b>\n{status}\nEntry: ₹{t['entry']:.2f} | Exit: ₹{exit_p:.2f}")
        else: rem.append(t)
    trades["active"] = rem
    return trades

def main():
    if not is_market_open(): return

    # VIX ਫਿਲਟਰ
    vix_df = fetch_data("^INDIAVIX")
    if vix_df is None or vix_df.empty: return
    vix = vix_df['close'].iloc[-1]
    if vix < 12.0 or vix > 22.0: return # ਸਿਰਫ਼ ਵਧੀਆ ਵਾਤਾਵਰਣ ਵਿੱਚ ਟ੍ਰੇਡ

    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        if not angel.generateSession(CLIENT_ID, PASSWORD, totp)['status']: return
    except: return

    if not os.path.exists("instruments.json"):
        r = requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json")
        with open("instruments.json", 'wb') as f: f.write(r.content)
    with open("instruments.json", 'r') as f: inst_df = pd.DataFrame(json.load(f))

    trades = load_trades()
    trades = check_trades(trades, angel)

    for name, info in INDEX_TOKENS.items():
        df = fetch_data(info["yahoo"])
        if df is None or len(df) < 30: continue
        
        ltp, ema9, ema21 = df['close'].iloc[-1], calc_ema(df['close'].tolist(), 9), calc_ema(df['close'].tolist(), 21)
        rsi = calc_rsi(df['close'].tolist(), 14)
        adx = calc_adx(df['high'].tolist(), df['low'].tolist(), df['close'].tolist(), 14)
        vwap, vol = df['vwap'].iloc[-1], df['vol'].iloc[-1]
        avg_vol = df['vol'].iloc[-21:-1].mean()

        if any(t["name"] == name for t in trades["active"]): continue # ਪਹਿਲਾਂ ਹੀ ਟ੍ਰੇਡ ਚੱਲ ਰਿਹਾ

        sig = None
        # CE: EMA >, RSI > 60, ADX > 22, Price > VWAP, Vol > Avg
        if ema9 > ema21 and rsi > 60 and adx > 22 and ltp > vwap and vol > avg_vol: sig = "CE"
        # PE: EMA <, RSI < 40, ADX > 22, Price < VWAP, Vol > Avg
        elif ema9 < ema21 and rsi < 40 and adx > 22 and ltp < vwap and vol > avg_vol: sig = "PE"

        if sig:
            step = info["step"]
            strike = round((ltp + step)/step)*step if sig == "CE" else round((ltp - step)/step)*step
            tok, sym, exch = find_option(name, strike, sig, inst_df)
            
            if tok:
                prem = get_ltp(angel, tok, exch)
                if prem > 0:
                    sl_d = prem * 0.25 # 25% SL
                    t1_d = sl_d * 2    # 1:2
                    t2_d = sl_d * 4    # 1:4
                    
                    trade = {
                        "name": name, "type": sig, "symbol": sym, "opt_token": tok, "exch": exch,
                        "entry": prem, "sl": prem - sl_d if sig=="CE" else prem + sl_d,
                        "t1": prem + t1_d if sig=="CE" else prem - t1_d,
                        "t2": prem + t2_d if sig=="CE" else prem - t2_d,
                        "status": "ACTIVE"
                    }
                    trades["active"].append(trade)
                    
                    qty = max(1, int(MAX_RISK_PER_TRADE / sl_d))
                    msg = f"🚀 <b>ਨਵਾਂ {sig} ਸਿਗਨਲ (V1.1)</b>\n\n📊 {name} ({ltp:.2f})\n🎯 {sym}\n"
                    msg += f"💰 Entry: ₹{prem:.2f}\n🛑 SL: ₹{trade['sl']:.2f}\n"
                    msg += f"🎯 T1 (1:2): ₹{trade['t1']:.2f}\n🎯 T2 (1:4): ₹{trade['t2']:.2f}\n"
                    msg += f"📦 Qty: {qty} (ਰਿਸਕ: ₹{qty*sl_d:.2f})"
                    send_telegram(msg)

    save_trades(trades)

if __name__ == "__main__":
    main()
