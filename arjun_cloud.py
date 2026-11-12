import urllib.request
import json
import ssl
import os
import time
import requests
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
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
    "NIFTY 50": {"token": "99926000", "symbol": "NIFTY", "exch": "NFO", "index_exch": "NSE", "yahoo": "^NSEI", "lot_size": 25},
    "BANK NIFTY": {"token": "99926009", "symbol": "BANKNIFTY", "exch": "NFO", "index_exch": "NSE", "yahoo": "^NSEBANK", "lot_size": 15},
    "SENSEX": {"token": "99919000", "symbol": "SENSEX", "exch": "BFO", "index_exch": "BSE", "yahoo": "^BSESN", "lot_size": 10} 
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

# ==================== GIST ਫਾਈਲ ਹੈਂਡਲਿੰਗ ====================
def load_trades():
    if not GIST_ID or not GIST_TOKEN: return {"active": [], "history": []}
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    try:
        res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        if res.status_code == 200:
            content = res.json()['files']['trades.json']['content']
            return json.loads(content)
    except Exception as e: print(f"Gist Read Error: {e}", flush=True)
    return {"active": [], "history": []}

def save_trades(trades):
    if not GIST_ID or not GIST_TOKEN: return
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    payload = {"files": {"trades.json": {"content": json.dumps(trades, indent=4)}}}
    try: requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload)
    except Exception as e: print(f"Gist Save Error: {e}", flush=True)

# ==================== ਗਲੋਬਲ ਮਾਰਕੀਟ ਅਤੇ ਖਬਰਾਂ ====================
def get_global_context():
    context = "🌍 <b>Global Market Context:</b>\n"
    try:
        # US Market (S&P 500)
        us = yf_data("^GSPC", "1d")
        us_change = ((us['close'].iloc[-1] - us['close'].iloc[-2]) / us['close'].iloc[-2]) * 100
        context += f"- US Market (S&P 500): {us_change:+.2f}%\n"
        
        # USD/INR
        inr = yf_data("INR=X", "1d")
        inr_val = inr['close'].iloc[-1]
        context += f"- USD/INR: ₹{inr_val:.2f}\n"
        
        # Crude Oil
        crude = yf_data("CL=F", "1d")
        crude_val = crude['close'].iloc[-1]
        context += f"- Crude Oil: ${crude_val:.2f}\n"
    except:
        context += "- ਗਲੋਬਲ ਡੇਟਾ ਉਪਲਬਧ ਨਹੀਂ ਹੈ।\n"
    
    # ਖਬਰਾਂ (Google News RSS)
    try:
        news_url = "https://news.google.com/rss/search?q=Nifty+50+Stock+Market&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(news_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if items:
                top_news = items[0].find('title').text
                context += f"\n📰 <b>Top News:</b> {top_news[:100]}...\n"
    except:
        pass
        
    return context

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ ====================
def yf_data(ticker, interval="1mo"):
    # ਪਿਛਲੇ 1 ਮਹੀਨੇ ਦਾ ਡੇਟਾ (ਪਿਛਲੇ ਦਿਨਾਂ ਦੇ ਹਿਸਾਬ ਲਈ)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range={interval}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            result = data['chart']['result'][0]
            q = result['indicators']['quote'][0]
            df = pd.DataFrame({'high': q['high'], 'low': q['low'], 'close': q['close']}).dropna()
            return df
    except: 
        return None

def calc_ema(prices, period):
    if len(prices) < period: return 0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

def calc_adx(df, period=14):
    if len(df) < period + 1: return 0
    highs, lows, closes = df['high'].tolist(), df['low'].tolist(), df['close'].tolist()
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    ap, am, at = sum(plus_dm[-period:])/period, sum(minus_dm[-period:])/period, sum(trs[-period:])/period
    if at == 0: return 0
    pdi, mdi = (ap/at)*100, (am/at)*100
    return abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0

def find_option_token(index_name, strike_price, option_type, instrument_df):
    symbol_name = INDEX_TOKENS[index_name]["symbol"]
    exch = INDEX_TOKENS[index_name]["exch"]
    target_strike = float(strike_price) * 100
    opts = instrument_df[(instrument_df['name'] == symbol_name) & (instrument_df['instrumenttype'] == 'OPTIDX') & (instrument_df['exch_seg'] == exch)].copy()
    if opts.empty: return None, None, None
    opts['strike_float'] = pd.to_numeric(opts['strike'], errors='coerce')
    match = opts[opts['strike_float'] == target_strike]
    if match.empty:
        avail = opts['strike_float'].dropna().unique()
        if len(avail) == 0: return None, None, None
        match = opts[opts['strike_float'] == min(avail, key=lambda x: abs(x - target_strike))]
    match = match[match['symbol'].str.endswith(option_type)]
    if match.empty: return None, None, None
    return match.iloc[0]['token'], match.iloc[0]['symbol'], exch

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
    if not is_market_open():
        print("ਮਾਰਕੀਟ ਬੰਦ ਹੈ। ਸਿਸਟਮ ਬੰਦ ਹੋ ਰਿਹਾ ਹੈ।", flush=True)
        return

    vix_df = yf_data("^INDIAVIX", "1d")
    if vix_df is None or vix_df.empty: return
    vix = vix_df['close'].iloc[-1]
    
    if vix < 10.0 or vix > 25.0:
        print(f"VIX ({vix:.2f}) ਖਤਰਨਾਕ ਲੈਵਲ 'ਤੇ ਹੈ। ਟ੍ਰੇਡ ਨਹੀਂ ਕਰਾਂਗੇ।", flush=True)
        return

    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = angel.generateSession(CLIENT_ID, PASSWORD, totp)
        if not data['status']: return
    except: return

    file_path = "instruments.json"
    if not os.path.exists(file_path):
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url)
        with open(file_path, 'wb') as f: f.write(response.content)
            
    with open(file_path, 'r') as f:
        instrument_df = pd.DataFrame(json.load(f))

    trades = load_trades()
    trades = check_active_trades(trades, angel)

    # 1. ਗਲੋਬਲ ਕਾਂਟੈਕਸਟ ਲਓ
    global_ctx = get_global_context()
    print("ਗਲੋਬਲ ਮਾਰਕੀਟ ਡੇਟਾ ਲੈ ਲਿਆ ਗਿਆ।", flush=True)
    
    # 2. ਸਕੈਨਿੰਗ
    for name, info in INDEX_TOKENS.items():
        print(f"-> {name} ਚੈੱਕ ਕਰ ਰਹੇ ਹਾਂ...", flush=True)
        df = yf_data(info["yahoo"], "1mo") # 1 ਮਹੀਨੇ ਦਾ ਡੇਟਾ
        
        if df is None or len(df) < 30: 
            print(f"   {name} ਲਈ ਡੇਟਾ ਘੱਟ ਹੈ।", flush=True)
            continue
        
        closes = df['close'].tolist()
        ltp = closes[-1]
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        rsi_series = [calc_rsi(closes[:i+1]) for i in range(len(closes)-2, len(closes))]
        rsi = rsi_series[-1]
        prev_rsi = rsi_series[-2]
        adx = calc_adx(df, 14)
        
        print(f"   RSI: {rsi:.1f}, ADX: {adx:.1f}", flush=True)

        new_signal = None
        if ema9 > ema21 and prev_rsi <= 55 and rsi > 55 and adx > 20: new_signal = "CE"
        elif ema9 < ema21 and prev_rsi >= 45 and rsi < 45 and adx > 20: new_signal = "PE"

        if new_signal and not any(t["name"] == name for t in trades["active"]):
            step = 50 if name == "NIFTY 50" else 100
            strike = round((ltp + step) / step) * step if new_signal == "CE" else round((ltp - step) / step) * step
            
            opt_token, opt_symbol, exch = find_option_token(name, strike, new_signal, instrument_df)
            
            if opt_token:
                entry_premium = get_option_ltp(angel, opt_token, exch)
                if entry_premium > 0:
                    sl_distance = entry_premium * 0.25 
                    target_distance = sl_distance * 3  
                    
                    sl_premium = entry_premium - sl_distance if new_signal == "CE" else entry_premium + sl_distance
                    target_premium = entry_premium + target_distance if new_signal == "CE" else entry_premium - target_distance

                    lot_size = info["lot_size"]
                    risk_per_lot = sl_distance * lot_size
                    
                    if risk_per_lot <= 300:
                        risk_status = "✅ ਘੱਟ ਰਿਸਕ (Low Risk)"
                    elif risk_per_lot <= 600:
                        risk_status = "⚠️ ਦਰਮਿਆਨਾ ਰਿਸਕ (Medium Risk)"
                    else:
                        risk_status = "🚨 ਵੱਧ ਰਿਸਕ (High Risk - ਧਿਆਨ ਨਾਲ!)"
                    
                    trade = {
                        "name": name, "type": new_signal, "symbol": opt_symbol,
                        "opt_token": opt_token, "exch": exch,
                        "entry_premium": entry_premium, "sl_premium": sl_premium, 
                        "target_premium": target_premium, "qty": lot_size,
                        "time": get_ist_time().strftime("%Y-%m-%d %H:%M")
                    }
                    trades["active"].append(trade)
                    
                    msg = f"🚀 <b>ਨਵਾਂ {new_signal} ਸਿਗਨਲ</b>\n\n"
                    msg += f"📊 {name} (₹{ltp:.2f})\n"
                    msg += f"🎯 {opt_symbol}\n"
                    msg += f"💰 Entry: ₹{entry_premium:.2f}\n"
                    msg += f"🛑 SL: ₹{sl_premium:.2f}\n"
                    msg += f"🎯 Target (1:3): ₹{target_premium:.2f}\n"
                    msg += f"📦 Qty: {lot_size} (1 Lot)\n"
                    msg += f"💵 <b>Total Risk: ₹{risk_per_lot:.2f}</b>\n"
                    msg += f"ℹ️ ਸਥਿਤੀ: {risk_status}\n\n"
                    msg += f"{global_ctx}" # ਗਲੋਬਲ ਡੇਟਾ ਵੀ ਨਾਲ ਭੇਜੋ
                    
                    send_telegram(msg)
                    print(f"   ✅ ਅਲਰਟ ਭੇਜ ਦਿੱਤਾ ਗਿਆ: {opt_symbol}", flush=True)
        else:
            print(f"   💤 ਕੋਈ ਸਿਗਨਲ ਨਹੀਂ ਬਣਿਆ। (RSI: {rsi:.1f}, ADX: {adx:.1f})", flush=True)

    save_trades(trades)
    print("ਸਕੈਨ ਪੂਰਾ ਹੋਇਆ।", flush=True)

if __name__ == "__main__":
    main()
