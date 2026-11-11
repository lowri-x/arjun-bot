import urllib.request
import json
import ssl
import os
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from SmartApi import SmartConnect
import pyotp

# ਇਹ ਕ੍ਰੈਡੈਂਸ਼ੀਅਲਜ਼ GitHub ਤੋਂ ਲਏ ਜਾਣਗੇ (ਕੋਡ ਵਿੱਚ ਨਹੀਂ ਲਿਖਣੇ ਪੈਣਗੇ)
API_KEY = os.environ.get("API_KEY")
CLIENT_ID = os.environ.get("CLIENT_ID")
PASSWORD = os.environ.get("PASSWORD")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

INDEX_TOKENS = {
    "NIFTY 50": {"token": "99926000", "symbol": "NIFTY", "exch": "NFO"},
    "BANK NIFTY": {"token": "99926009", "symbol": "BANKNIFTY", "exch": "NFO"},
    "SENSEX": {"token": "99919000", "symbol": "SENSEX", "exch": "BFO"} 
}

def is_market_open():
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
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
    closest = match.iloc[0]
    return closest['token'], closest['symbol'], exch

def get_option_ltp(angel, token, exch):
    try:
        data = angel.ltpData(exch, "", token)
        if data['status']: return data['data']['ltp']
    except: return 0

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
    for p in prices[1:]:
        ema = (p * alpha) + (ema * (1 - alpha))
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

def main():
    if not is_market_open():
        print("ਮਾਰਕੀਟ ਬੰਦ ਹੈ।")
        return

    print("Angel One ਨਾਲ ਜੁੜ ਰਹੇ ਹਾਂ...")
    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = angel.generateSession(CLIENT_ID, PASSWORD, totp)
        if not data['status']:
            print("ਲੌਗਇਨ ਫੇਲ।")
            return
    except Exception as e:
        print(f"Error: {e}")
        return

    # ਡਾਟਾ ਲੋਡ ਕਰੋ
    file_path = "instruments.json"
    if not os.path.exists(file_path):
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url)
        with open(file_path, 'wb') as f:
            f.write(response.content)
            
    with open(file_path, 'r') as f:
        instrument_df = pd.DataFrame(json.load(f))

    print("ਸਕੈਨ ਕਰ ਰਹੇ ਹਾਂ...")
    yahoo_map = {"NIFTY 50": "^NSEI", "BANK NIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    
    for name, ticker in yahoo_map.items():
        closes = fetch_yahoo(ticker)
        if not closes or len(closes) < 30: continue
        
        ltp = closes[-1]
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        rsi_series = calc_rsi_series(closes, 14)
        rsi = rsi_series[-1]
        prev_rsi = rsi_series[-2]

        # ਸਿਰਫ਼ ਤਦ ਹੀ ਅਲਰਟ ਭੇਜੋ ਜਦੋਂ RSI 60 ਤੋਂ ਉੱਪਰ ਕਰਾਸ ਕਰੇ (CE) ਜਾਂ 40 ਤੋਂ ਹੇਠਾਂ ਕਰਾਸ ਕਰੇ (PE)
        new_signal = None
        if ema9 > ema21 and prev_rsi <= 60 and rsi > 60: new_signal = "CE"
        elif ema9 < ema21 and prev_rsi >= 40 and rsi < 40: new_signal = "PE"

        if new_signal:
            step = 50 if name == "NIFTY 50" else (100 if name == "BANK NIFTY" else 100)
            strike = round((ltp + step) / step) * step if new_signal == "CE" else round((ltp - step) / step) * step
            opt_token, opt_symbol, exch = find_option_token(name, strike, new_signal, instrument_df)
            
            if opt_token:
                premium = get_option_ltp(angel, opt_token, exch)
                msg = f"🚀 <b>ਕਲਾਉਡ ਸਿਗਨਲ ({new_signal})</b>\n\n"
                msg += f"📊 ਇੰਡੈਕਸ: <b>{name}</b> (₹{ltp:.2f})\n"
                msg += f"🎯 ਸਟ੍ਰਾਈਕ: <b>{opt_symbol}</b>\n"
                msg += f"💰 Premium: <b>₹{premium:.2f}</b>\n"
                msg += f"📈 RSI: {rsi:.1f}"
                send_telegram(msg)
                print(f"ਅਲਰਟ ਭੇਜਿਆ: {name} - {opt_symbol}")

if __name__ == "__main__":
    main()