# live_feed.py
import time
import logging
from datetime import datetime, timedelta
import pyotp
import requests
import pandas as pd
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config import *

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- TELEGRAM ALERT FUNCTION ---
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

# --- ANGEL ONE LOGIN ---
def login_angel_one():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    data = obj.generateSession(CLIENT_ID, PIN, totp)
    if data['status']:
        logging.info("Angel One Login Successful")
        return obj
    else:
        logging.error("Angel One Login Failed")
        return None

# --- WEBSOCKET & CANDLE BUILDER ---
class LiveDataEngine:
    def __init__(self, smart_obj):
        self.smart_obj = smart_obj
        self.feed_token = self.smart_obj.getfeedToken()
        self.sws = SmartWebSocketV2(self.smart_obj.generateSession(CLIENT_ID, PIN, pyotp.TOTP(TOTP_SECRET).now())['data']['jwtToken'], 
                                    self.smart_obj.generateSession(CLIENT_ID, PIN, pyotp.TOTP(TOTP_SECRET).now())['data']['refreshToken'], 
                                    self.feed_token, API_KEY, CLIENT_ID)
        
        self.token_to_symbol = {v: k for k, v in STOCKS_TO_TRACK.items()}
        self.candles = {token: [] for token in STOCKS_TO_TRACK.values()} # Store 5m candles
        self.current_candle = {token: None for token in STOCKS_TO_TRACK.values()}
        self.last_alert_time = {token: None for token in STOCKS_TO_TRACK.values()}

        # Subscribe to tokens
        self.token_list = [{"exchangeType": 1, "tokens": list(STOCKS_TO_TRACK.values())}]

    def on_open(self, wsapp):
        logging.info("WebSocket Connection Opened")
        self.sws.subscribe("abc123", 1, self.token_list)

    def on_data(self, wsapp, message):
        if message['type'] == 'sf' or message['type'] == 'tf': # Snapquote or Tick
            token = str(message['token'])
            ltp = message['last_traded_price'] / 100.0 # Price comes in paise
            volume = message.get('volume_trade_for_the_day', 0)
            
            if token not in self.token_to_symbol: return
            
            now = datetime.now()
            # 5-minute timeframe (Round down to nearest 5 mins)
            candle_time = now - timedelta(minutes=now.minute % 5, seconds=now.second, microseconds=now.microsecond)
            
            if self.current_candle[token] is None or self.current_candle[token]['time'] != candle_time:
                # New Candle Period
                if self.current_candle[token] is not None:
                    # Finalize previous candle
                    self.candles[token].append(self.current_candle[token])
                    self.evaluate_strategy(token, self.current_candle[token])
                    if len(self.candles[token]) > 50: # Keep only last 50 candles
                        self.candles[token].pop(0)
                
                self.current_candle[token] = {
                    'time': candle_time, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp, 'volume': volume
                }
            else:
                # Update current candle
                self.current_candle[token]['high'] = max(self.current_candle[token]['high'], ltp)
                self.current_candle[token]['low'] = min(self.current_candle[token]['low'], ltp)
                self.current_candle[token]['close'] = ltp
                self.current_candle[token]['volume'] = volume

    def on_error(self, wsapp, error):
        logging.error(f"WebSocket Error: {error}")

    def on_close(self, wsapp):
        logging.info("WebSocket Closed")

    def evaluate_strategy(self, token, current_candle):
        symbol = self.token_to_symbol[token]
        history = self.candles[token]
        
        if len(history) < LOOKBACK_PERIOD + 1: 
            return # Not enough data yet
            
        # Get past 20 candles (excluding the current one that just closed)
        past_20 = history[-(LOOKBACK_PERIOD + 1):-1]
        
        high_20 = max(c['high'] for c in past_20)
        low_20 = min(c['low'] for c in past_20)
        
        # Calculate average volume, avoiding division by zero (AI 1's fix)
        avg_vol = sum(c['volume'] for c in past_20) / LOOKBACK_PERIOD
        if avg_vol == 0: avg_vol = 1 
        
        current_vol = current_candle['volume']
        current_close = current_candle['close']
        
        # Breakout logic
        is_volume_surge = current_vol > (avg_vol * VOLUME_MULTIPLIER)
        
        signal = None
        if current_close > high_20 and is_volume_surge:
            signal = "BUY (CE)"
        elif current_close < low_20 and is_volume_surge:
            signal = "SELL (PE)"
            
        if signal:
            # Prevent multiple alerts for the same candle
            if self.last_alert_time[token] == current_candle['time']:
                return
            self.last_alert_time[token] = current_candle['time']
            
            sl = current_candle['low'] if "BUY" in signal else current_candle['high']
            target = current_close + (abs(current_close - sl) * 1.5) if "BUY" in signal else current_close - (abs(sl - current_close) * 1.5)
            
            msg = (f"🚨 <b>LIVE SIGNAL: {symbol}</b> 🚨\n\n"
                   f"Direction: <b>{signal}</b>\n"
                   f"Entry: ₹{current_close:.2f}\n"
                   f"Stop Loss: ₹{sl:.2f}\n"
                   f"Target (1:1.5): ₹{target:.2f}\n"
                   f"Volume Surge: {current_vol/avg_vol:.1f}x\n\n"
                   f"<i>Action: Manual Entry Only</i>")
            
            logging.info(f"Signal Generated: {msg}")
            send_telegram_alert(msg)

    def start(self):
        self.sws.on_open = self.on_open
        self.sws.on_data = self.on_data
        self.sws.on_error = self.on_error
        self.sws.on_close = self.on_close
        self.sws.connect()

if __name__ == "__main__":
    send_telegram_alert("✅ <b>ARJUN Live Signal Engine Started</b>\nScanning S&R Breakouts...")
    obj = login_angel_one()
    if obj:
        engine = LiveDataEngine(obj)
        try:
            engine.start()
        except KeyboardInterrupt:
            send_telegram_alert("🛑 <b>ARJUN Live Signal Engine Stopped</b>")
