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

def main():
    print("1. ਸਿਸਟਮ ਸ਼ੁਰੂ ਹੋਇਆ...", flush=True)
    
    if not is_market_open():
        print("ਮਾਰਕੀਟ ਬੰਦ ਹੈ।", flush=True)
        return
    print("2. ਮਾਰਕੀਟ ਖੁੱਲ੍ਹੀ ਹੈ।", flush=True)

    # VIX ਚੈੱਕ
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^INDIAVIX?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            vix = data['chart']['result'][0]['indicators']['quote'][0]['close'][-1]
            print(f"3. VIX ਕੀਮਤ: {vix}", flush=True)
            if vix < 12.0 or vix > 25.0:
                print(f"VIX ({vix:.2f}) ਖਤਰਨਾਕ ਲੈਵਲ 'ਤੇ ਹੈ। ਟ੍ਰੇਡ ਨਹੀਂ ਕਰਾਂਗੇ।", flush=True)
                return
    except Exception as e:
        print(f"VIX ਡੇਟਾ ਫੇਲ: {e}", flush=True)
        return

    print("4. Angel One ਨਾਲ ਜੁੜ ਰਹੇ ਹਾਂ...", flush=True)
    angel = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = angel.generateSession(CLIENT_ID, PASSWORD, totp)
        if not data['status']:
            print(f"ਲੌਗਇਨ ਫੇਲ: {data}", flush=True)
            return
        print("5. Angel One ਲੌਗਇਨ ਸਫਲ!", flush=True)
    except Exception as e:
        print(f"ਲੌਗਇਨ ਐਰਰ: {e}", flush=True)
        return

    print("6. ਇੰਸਟਰੂਮੈਂਟ ਡਾਟਾ ਚੈੱਕ ਕਰ ਰਹੇ ਹਾਂ...", flush=True)
    file_path = "instruments.json"
    if not os.path.exists(file_path):
        print("ਇੰਸਟਰੂਮੈਂਟ ਫਾਈਲ ਡਾਊਨਲੋਡ ਹੋ ਰਹੀ ਹੈ (ਇਸ ਵਿੱਚ ਸਮਾਂ ਲੱਗੇਗਾ)...", flush=True)
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        try:
            response = requests.get(url, timeout=30)
            with open(file_path, 'wb') as f: f.write(response.content)
            print("ਡਾਊਨਲੋਡ ਪੂਰਾ ਹੋਇਆ!", flush=True)
        except Exception as e:
            print(f"ਡਾਊਨਲੋਡ ਫੇਲ: {e}", flush=True)
            return
            
    print("7. ਸਕੈਨਿੰਗ ਸ਼ੁਰੂ ਕਰ ਰਹੇ ਹਾਂ (ਬਾਕੀ ਲਾਜਿਕ)...", flush=True)
    # ਬਾਕੀ ਦਾ ਸਾਰਾ ਲਾਜਿਕ ਇੱਥੇ ਹੀ ਹੈ...
    print("ਸਿਸਟਮ ਖਤਮ ਹੋਇਆ।", flush=True)

if __name__ == "__main__":
    main()
