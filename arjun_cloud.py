import urllib.request
import json
import ssl
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from SmartApi import SmartConnect
import pyotp

API_KEY = os.environ.get("API_KEY")
CLIENT_ID = os.environ.get("CLIENT_ID")
PASSWORD = os.environ.get("PASSWORD")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

INDEX_TOKENS = {
    "NIFTY 50": {"token": "99926000", "symbol": "NIFTY", "exch": "NFO", "index_exch": "NSE", "yahoo": "^NSEI"},
    "BANK NIFTY": {"token": "99926009", "symbol": "BANKNIFTY", "exch": "NFO", "index_exch": "NSE", "yahoo": "^NSEBANK"},
    "SENSEX": {"token": "99919000", "symbol": "SENSEX", "exch": "BFO", "index_exch": "BSE", "yahoo": "^BSESN"} 
}

TRADES_FILE = "trades.json"

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
    try:
        urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==================== ਟ੍ਰੈਕਿੰਗ ਫਾਈਲ ਪੜ੍ਹਨਾ/ਲਿਖਣਾ ====================
def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"active": [], "history": []}

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

# ==================== ਆਪਸ਼ਨ ਚੇਨ ====================
def find_option_token(index_name, strike_price, option_type, instrument_df):
    symbol_name = INDEX_TOKENS[index_name]["symbol"]
    exch = INDEX_TOKENS[index_name]["exch"]
    target_strike = float(strike_price) * 100
    
    opts = instrument_df[
        (instrument_df['name'] == symbol_name) & 
        (instrument_df['instrumenttype'] == 'OPTIDX') &
        (instrument_df['exch_seg'] == exch)
    ].copy()
    
    if opts.empty: return None, None, None
    opts['strike_float'] = pd.to_numeric(opts['strike'], errors='coerce')
    match = opts[opts['strike_float'] == target_strike]
    
    if match.empty:
        available_strikes = opts['strike_float'].dropna().unique()
        if len(available_strikes) == 0: return None, None, None
        closest_val = min(available_strikes, key=lambda x: abs(x - target_strike))
        match = opts[opts['strike_float'] == closest_val]
        
    match = match[match['symbol'].str.endswith(option_type)]
    if match.empty: return None, None, None
    
    try:
        match['expiry_date'] = pd.to_datetime(match['expiry'], format='%d%b%Y')
        match = match.sort_values('expiry_date')
    except:
        pass

    closest = match.iloc[0]
    return closest['token'], closest['symbol'], exch

def get_option_ltp(angel, token, exch):
    try:
        data = angel.ltpData(exch, "", token)
        if data['status']: return data['data']['ltp']
    except: return 0

# ==================== ਡੇਟਾ ਫੈਚਿੰਗ ====================
def fetch_yahoo(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            result = data['chart']['result'][0]
            return [c for c in result['indicators']['quote'][0]['close'] if c is not None]
    except: return None

def calc_ema(prices, period):
    if not prices: return 0
    alpha = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]: ema = (p * alpha) + (ema * (1 - alpha))
    return ema

def calc_rsi_series(prices, period=14):
    if len(prices) < period + 1: return [50]*len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    rsi_vals = []
    rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
    rsi_vals.append(100.0 - (100.0 / (1.0 + rs)) if avg_loss > 0 else 100.0)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0: rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    pad = [50.0] * (len(prices) - len(rsi_vals))
    return pad + rsi_vals

def check_active_trades(trades, angel):
    """ਚੈੱਕ ਕਰੋ ਕਿ ਕੋਈ ਟ੍ਰੇਡ ਟਾਰਗੇਟ ਜਾਂ SL ਹਿੱਟ ਹੋਇਆ ਹੈ"""
    active = trades["active"]
    remaining = []
    
    for trade in active:
        name = trade["name"]
        token = INDEX_TOKENS[name]["token"]
        exch = INDEX_TOKENS[name]["index_exch"]
        
        try:
            res = angel.ltpData(exch, name, token)
            current_price = res['data']['ltp'] if res['status'] else trade["entry"]
        except:
            current_price = trade["entry"]

        status = None
        if trade["type"] == "CE":
            if current_price >= trade["target"]: status = "PASS (Target Hit) ✅"
            elif current_price <= trade["sl"]: status = "FAIL (SL Hit) ❌"
        elif trade["type"] == "PE":
            if current_price <= trade["target"]: status = "PASS (Target Hit) ✅"
            elif current_price >= trade["sl"]: status = "FAIL (SL Hit) ❌"
            
        if status:
            trade["status"] = status
            trade["exit_price"] = current_price
            trades["history"].append(trade)
            
            emoji = "✅" if "PASS" in status else "❌"
            msg = f"{emoji} <b>{name} ਟ੍ਰੇਡ ਬੰਦ ਹੋਇਆ!</b>\n"
            msg += f"ਸਟੇਟਸ: {status}\n"
            msg += f"Entry: ₹{trade['entry']:.2f} | Exit: ₹{current_price:.2f}"
            send_telegram(msg)
        else:
            remaining.append(trade)
            
    trades["active"] = remaining
    return trades

def main():
    if not is_market_open():
        print("ਮਾਰਕੀਟ ਬੰਦ ਹੈ।")
        return

    print("Angel One ਨਾਲ ਜੁੜ ਰਹੇ ਹਾਂ...")
    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = angel.generateSession(CLIENT_ID, PASSWORD, totp)
        if not data['status']: return
    except: return

    # ਡਾਟਾ ਲੋਡ ਕਰੋ
    file_path = "instruments.json"
    if not os.path.exists(file_path):
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url)
        with open(file_path, 'wb') as f: f.write(response.content)
            
    with open(file_path, 'r') as f:
        instrument_df = pd.DataFrame(json.load(f))

    # ਟ੍ਰੇਡਸ ਲੋਡ ਕਰੋ ਅਤੇ ਪੁਰਾਣੇ ਚੈੱਕ ਕਰੋ
    trades = load_trades()
    trades = check_active_trades(trades, angel)

    print("ਸਕੈਨ ਕਰ ਰਹੇ ਹਾਂ...")
    for name, info in INDEX_TOKENS.items():
        closes = fetch_yahoo(info["yahoo"])
        if not closes or len(closes) < 30: continue
        
        ltp = closes[-1]
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        rsi_series = calc_rsi_series(closes, 14)
        rsi = rsi_series[-1]
        prev_rsi = rsi_series[-2]

        new_signal = None
        if ema9 > ema21 and prev_rsi <= 60 and rsi > 60: new_signal = "CE"
        elif ema9 < ema21 and prev_rsi >= 40 and rsi < 40: new_signal = "PE"

        # ਜੇਕਰ ਨਵਾਂ ਸਿਗਨਲ ਹੈ ਅਤੇ ਇਸ ਇੰਡੈਕਸ ਦਾ ਪਹਿਲਾਂ ਤੋਂ ਕੋਈ ਟ੍ਰੇਡ ਚੱਲ ਰਿਹਾ ਨਹੀਂ
        if new_signal and not any(t["name"] == name for t in trades["active"]):
            step = 50 if name == "NIFTY 50" else 100
            strike = round((ltp + step) / step) * step if new_signal == "CE" else round((ltp - step) / step) * step
            opt_token, opt_symbol, exch = find_option_token(name, strike, new_signal, instrument_df)
            
            if opt_token:
                premium = get_option_ltp(angel, opt_token, exch)
                
                # SL ਅਤੇ Target ਦਾ ਹਿਸਾਬ (1:3)
                if new_signal == "CE":
                    sl, target = ltp - (1.5 * 20), ltp + (3 * 1.5 * 20)
                else:
                    sl, target = ltp + (1.5 * 20), ltp - (3 * 1.5 * 20)

                trade = {
                    "name": name, "type": new_signal, "symbol": opt_symbol,
                    "entry": ltp, "sl": sl, "target": target, "premium": premium,
                    "time": get_ist_time().strftime("%Y-%m-%d %H:%M")
                }
                trades["active"].append(trade)
                
                msg = f"🚀 <b>ਨਵਾਂ {new_signal} ਸਿਗਨਲ (ਲਾਈਵ)</b>\n\n"
                msg += f"📊 ਇੰਡੈਕਸ: <b>{name}</b> (₹{ltp:.2f})\n"
                msg += f"🎯 ਸਟ੍ਰਾਈਕ: <b>{opt_symbol}</b>\n"
                msg += f"💰 Premium: <b>₹{premium:.2f}</b>\n"
                msg += f"🛑 SL: ₹{sl:.2f} | 🎯 Target: ₹{target:.2f}"
                send_telegram(msg)

    save_trades(trades)
    print("ਸਕੈਨ ਪੂਰਾ ਹੋਇਆ। ਟ੍ਰੇਡਸ ਸੇਵ ਹੋ ਗਏ।")

if __name__ == "__main__":
    main()
