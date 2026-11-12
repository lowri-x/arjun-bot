import urllib.request
import json
import ssl
import os
import time
import requests
import pandas as pd
import numpy as np
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

# ਹੁਣ ਸਿਰਫ਼ Nifty ਅਤੇ Bank Nifty ਹੀ ਹਨ (Sensex ਹਟਾ ਦਿੱਤਾ ਗਿਆ ਹੈ)
INDEX_TOKENS = {
    "NIFTY 50": {"token": "99926000", "symbol": "NIFTY", "exch": "NFO", "index_exch": "NSE", "step": 50, "default_lot": 25},
    "BANK NIFTY": {"token": "99926009", "symbol": "BANKNIFTY", "exch": "NFO", "index_exch": "NSE", "step": 100, "default_lot": 15}
}

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
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try: urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e: print(f"Telegram Error: {e}", flush=True)

# ==================== GIST ਹੈਂਡਲਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200:
            return json.loads(res.json()['files']['trades.json']['content'])
    except: pass
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except: pass

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ (Angel One ਤੋਂ) ====================
def fetch_angel_candles(angel, token, exch, interval):
    from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    try:
        # API ਦੀ ਰੇਟ ਲਿਮਿਟ ਤੋਂ ਬਚਣ ਲਈ 2 ਸਕਿੰਟ ਦਾ ਸਮਾਂ
        time.sleep(2.0) 
        data = angel.getCandleData({
            "exchange": exch,
            "symboltoken": token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date
        })
        
        if data and isinstance(data, dict) and data.get('status') == True and isinstance(data.get('data'), list) and len(data['data']) > 0:
            df = pd.DataFrame(data['data'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            numeric_cols = ['open', 'high', 'low', 'close']
            df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
            df = df.dropna(subset=numeric_cols)
            
            last_time_str = "Unknown"
            if not df.empty:
                last_ts = data['data'][-1][0]
                if isinstance(last_ts, str):
                    last_ts = float(last_ts)
                
                last_time = datetime.fromtimestamp(last_ts / 1000, timezone.utc) + timedelta(hours=5, minutes=30)
                last_time_str = last_time.strftime("%H:%M")
                
            return df[['open', 'high', 'low', 'close']], last_time_str
        else:
            print(f"Angel API Error ({token}): Invalid or empty data.", flush=True)
            
    except Exception as e:
        print(f"Angel API Exception ({token}): {e}", flush=True)
    return None, None

# ==================== ਇੰਡੀਕੇਟਰਜ਼ ====================
def add_indicators(df):
    df = df.copy()
    close, high, low, open_ = df["close"], df["high"], df["low"], df["open"]
    
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
    
    df["plus_di"] = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / atr_smooth
    df["minus_di"] = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / atr_smooth
    dx = 100 * (df["plus_di"] - df["minus_di"]).abs() / (df["plus_di"] + df["minus_di"]).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()

    hl2 = (high + low) / 2
    upper = (hl2 + 3.0 * df["atr"]).to_numpy()
    lower = (hl2 - 3.0 * df["atr"]).to_numpy()
    c = close.to_numpy()
    st = np.zeros(len(df))
    trend = np.ones(len(df), dtype=int)

    for i in range(1, len(df)):
        if c[i-1] > upper[i-1]: lower[i] = max(lower[i], lower[i-1]) if trend[i-1]==1 else lower[i]
        if c[i-1] < lower[i-1]: upper[i] = min(upper[i], upper[i-1]) if trend[i-1]==-1 else upper[i]
        
        if trend[i-1] == 1:
            if c[i] < lower[i]: trend[i] = -1; st[i] = upper[i]
            else: trend[i] = 1; st[i] = lower[i]
        else:
            if c[i] > upper[i]: trend[i] = 1; st[i] = lower[i]
            else: trend[i] = -1; st[i] = upper[i]
            
    df["st_dir"] = trend

    body = (close - open_).abs()
    candle_range = (high - low).replace(0, np.nan)
    upper_wick = high - np.maximum(open_, close)
    lower_wick = np.minimum(open_, close) - low
    
    prev_bull = close.shift(1) > open_.shift(1)
    prev_bear = close.shift(1) < open_.shift(1)
    curr_bull = close > open_
    curr_bear = close < open_

    df["pat_bull_engulf"] = prev_bear & curr_bull & (close >= open_.shift(1)) & (open_ <= close.shift(1)) & (body > body.shift(1))
    df["pat_bear_engulf"] = prev_bull & curr_bear & (close <= open_.shift(1)) & (open_ >= close.shift(1)) & (body > body.shift(1))
    df["pat_hammer"] = (lower_wick >= 2.0 * body) & (upper_wick <= 0.3 * candle_range)
    df["pat_shooting_star"] = (upper_wick >= 2.0 * body) & (lower_wick <= 0.3 * candle_range)
    
    return df

# ==================== ਆਪਸ਼ਨ ਚੇਨ ====================
def find_option_token(index_name, strike_price, option_type, instrument_df):
    symbol_name = INDEX_TOKENS[index_name]["symbol"]
    exch = INDEX_TOKENS[index_name]["exch"]
    target_strike = float(strike_price) * 100
    opts = instrument_df[(instrument_df['name'] == symbol_name) & (instrument_df['instrumenttype'] == 'OPTIDX') & (instrument_df['exch_seg'] == exch)].copy()
    if opts.empty: return None, None, None, INDEX_TOKENS[index_name]["default_lot"]
    
    opts['strike_float'] = pd.to_numeric(opts['strike'], errors='coerce')
    match = opts[opts['strike_float'] == target_strike]
    
    if match.empty:
        avail = opts['strike_float'].dropna().unique()
        if len(avail) == 0: return None, None, None, INDEX_TOKENS[index_name]["default_lot"]
        match = opts[opts['strike_float'] == min(avail, key=lambda x: abs(x - target_strike))]
        
    match = match[match['symbol'].str.endswith(option_type)]
    if match.empty: return None, None, None, INDEX_TOKENS[index_name]["default_lot"]
    
    try: lot_size = int(float(match.iloc[0]['lotsize']))
    except: lot_size = INDEX_TOKENS[index_name]["default_lot"]
        
    return match.iloc[0]['token'], match.iloc[0]['symbol'], exch, lot_size

def get_option_ltp(angel, token, exch):
    try:
        data = angel.ltpData(exch, "", token)
        if data['status']: return data['data']['ltp']
    except: return 0

# ==================== ਟ੍ਰੇਡ ਟ੍ਰੈਕਿੰਗ ====================
def check_active_trades(trades, angel):
    remaining = []
    for trade in trades["active"]:
        current_premium = get_option_ltp(angel, trade["opt_token"], trade["exch"])
        if current_premium == 0:
            remaining.append(trade)
            continue

        status = None
        if trade["type"] == "CE":
            if current_premium >= trade["target_premium"]: status = "PASS (Target Hit) ✅"
            elif current_premium <= trade["sl_premium"]: status = "FAIL (SL Hit) ❌"
        elif trade["type"] == "PE":
            if current_premium <= trade["target_premium"]: status = "PASS (Target Hit) ✅"
            elif current_premium >= trade["sl_premium"]: status = "FAIL (SL Hit) ❌"
            
        if status:
            trade["status"] = status
            trade["exit_premium"] = current_premium
            trades["history"].append(trade)
            emoji = "✅" if "PASS" in status else "❌"
            msg = f"{emoji} <b>{trade['name']} ਟ੍ਰੇਡ ਬੰਦ ਹੋਇਆ!</b>\nਸਟੇਟਸ: {status}\nEntry: ₹{trade['entry_premium']:.2f} | Exit: ₹{current_premium:.2f}"
            send_telegram(msg)
        else:
            remaining.append(trade)
    trades["active"] = remaining
    return trades

# ==================== ਮੁੱਖ ਲੂਪ ====================
def main():
    if not is_market_open(): return

    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        if not angel.generateSession(CLIENT_ID, PASSWORD, totp)['status']: return
        print("Angel One ਲੌਗਇਨ ਸਫਲ!", flush=True)
    except Exception as e:
        print(f"Angel One ਲੌਗਇਨ ਫੇਲ: {e}", flush=True)
        return

    file_path = "instruments.json"
    if not os.path.exists(file_path):
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url)
        with open(file_path, 'wb') as f: f.write(response.content)
            
    with open(file_path, 'r') as f:
        instrument_df = pd.DataFrame(json.load(f))

    trades = load_trades()
    trades = check_active_trades(trades, angel)

    current_time_str = get_ist_time().strftime("%H:%M")

    for name, info in INDEX_TOKENS.items():
        print(f"-> {name} ਲਈ ਡੇਟਾ ਲੈ ਰਹੇ ਹਾਂ...", flush=True)
        
        df_15, time_15 = fetch_angel_candles(angel, info["token"], info["index_exch"], "FIFTEEN_MINUTE")
        df_5, time_5 = fetch_angel_candles(angel, info["token"], info["index_exch"], "FIVE_MINUTE")
        
        if df_15 is None or df_5 is None or len(df_5) < 30: 
            print(f"-> {name}: ਡੇਟਾ ਨਹੀਂ ਮਿਲਿਆ।", flush=True)
            continue
        
        df_15 = add_indicators(df_15)
        df_5 = add_indicators(df_5)
        
        c5, p5, c15 = df_5.iloc[-1], df_5.iloc[-2], df_15.iloc[-1]
        
        htf_bull = (c15["close"] > c15["ema21"]) and (c15["st_dir"] == 1)
        htf_bear = (c15["close"] < c15["ema21"]) and (c15["st_dir"] == -1)
        
        adx_expanding = (c5["adx"] > 14.0) and (c5["adx"] > p5["adx"])
        bull_candle = bool(c5["pat_bull_engulf"] or c5["pat_hammer"] or (c5["close"] > p5["high"]))
        bear_candle = bool(c5["pat_bear_engulf"] or c5["pat_shooting_star"] or (c5["close"] < p5["low"]))

        new_signal = None
        
        if htf_bull and (c5["ema9"] > c5["ema21"]) and (52 <= c5["rsi"] <= 75) and adx_expanding and (c5["plus_di"] > c5["minus_di"]) and bull_candle:
            new_signal = "CE"
        elif htf_bear and (c5["ema9"] < c5["ema21"]) and (25 <= c5["rsi"] <= 48) and adx_expanding and (c5["minus_di"] > c5["plus_di"]) and bear_candle:
            new_signal = "PE"

        if new_signal and not any(t["name"] == name for t in trades["active"]):
            step = info["step"]
            strike = round((c5['close'] + step) / step) * step if new_signal == "CE" else round((c5['close'] - step) / step) * step
            
            opt_token, opt_symbol, exch, lot_size = find_option_token(name, strike, new_signal, instrument_df)
            
            if opt_token and lot_size > 0:
                entry_premium = get_option_ltp(angel, opt_token, exch)
                if entry_premium > 0:
                    atr_risk = 1.5 * c15["atr"] * 0.5
                    sl_distance = min(atr_risk, entry_premium * 0.25)
                    
                    sl_premium = entry_premium - sl_distance if new_signal == "CE" else entry_premium + sl_distance
                    target_premium = entry_premium + (1.5 * sl_distance) if new_signal == "CE" else entry_premium - (1.5 * sl_distance)

                    risk_per_lot = sl_distance * lot_size
                    
                    if risk_per_lot <= 300: risk_status = "✅ ਘੱਟ ਰਿਸਕ"
                    elif risk_per_lot <= 600: risk_status = "⚠️ ਦਰਮਿਆਨਾ ਰਿਸਕ"
                    else: risk_status = "🚨 ਵੱਧ ਰਿਸਕ"
                    
                    trade = {
                        "name": name, "type": new_signal, "symbol": opt_symbol,
                        "opt_token": opt_token, "exch": exch,
                        "entry_premium": entry_premium, "sl_premium": sl_premium, 
                        "target_premium": target_premium, "qty": lot_size,
                        "time": get_ist_time().strftime("%Y-%m-%d %H:%M")
                    }
                    trades["active"].append(trade)
                    
                    msg = f"🚀 <b>ਨਵਾਂ {new_signal} ਸਿਗਨਲ (MTF)</b>\n\n"
                    msg += f"⏰ <b>ਡੇਟਾ ਸਮਾਂ:</b> {time_5} ਵਜੇ ਦਾ (5m)\n"
                    msg += f"⏰ <b>ਅਲਰਟ ਸਮਾਂ:</b> {current_time_str} ਵਜੇ\n\n"
                    msg += f"📊 {name} (₹{c5['close']:.2f})\n"
                    msg += f"🎯 {opt_symbol}\n"
                    msg += f"💰 Entry: ₹{entry_premium:.2f}\n"
                    msg += f"🛑 SL: ₹{sl_premium:.2f}\n"
                    msg += f"🎯 Target (1.5R): ₹{target_premium:.2f}\n"
                    msg += f"📦 Qty: {lot_size} (1 Lot)\n"
                    msg += f"💵 <b>Total Risk: ₹{risk_per_lot:.2f}</b>\n"
                    msg += f"ℹ️ ਸਥਿਤੀ: {risk_status}"
                    send_telegram(msg)
                    print(f"-> {name}: ✅ ਸਿਗਨਲ ਮਿਲਿਆ - {new_signal} (Data: {time_5})", flush=True)
            else:
                print(f"-> {name}: ਸਟ੍ਰਾਈਕ {strike} ਨਹੀਂ ਮਿਲਿਆ।", flush=True)
        else:
            if c5["rsi"] >= 52: search_type = "CE (Call)"
            elif c5["rsi"] <= 48: search_type = "PE (Put)"
            else: search_type = "Neutral"
            
            print(f"-> {name}: {search_type} ਲੱਭ ਰਹੇ ਹਾਂ... (ਡੇਟਾ: {time_5} ਵਜੇ ਦਾ | RSI: {c5['rsi']:.1f}, ADX: {c5['adx']:.1f})", flush=True)

    save_trades(trades)

if __name__ == "__main__":
    main()
