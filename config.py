# master_bot.py
import time
import logging
from datetime import datetime, timedelta
import pyotp
import requests
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
class NiftyBreakoutEngine:
    def __init__(self, smart_obj):
        self.smart_obj = smart_obj
        self.feed_token = self.smart_obj.getfeedToken()
        session_data = self.smart_obj.generateSession(CLIENT_ID, PIN, pyotp.TOTP(TOTP_SECRET).now())['data']
        
        self.sws = SmartWebSocketV2(session_data['jwtToken'], session_data['refreshToken'], self.feed_token, API_KEY, CLIENT_ID)
        
        self.token_to_symbol = {v: k for k, v in INDICES_TO_TRACK.items()}
        self.candles = {token: [] for token in INDICES_TO_TRACK.values()} 
        self.current_candle = {token: None for token in INDICES_TO_TRACK.values()}
        self.last_alert_time = {token: None for token in INDICES_TO_TRACK.values()}

        # Subscribe to tokens (Exchange Type 1 = NSE)
        self.token_list = [{"exchangeType": 1, "tokens": list(INDICES_TO_TRACK.values())}]

    def on_open(self, wsapp):
        logging.info("WebSocket Connection Opened for Nifty & BankNifty")
        self.sws.subscribe("nifty_bot", 1, self.token_list)

    def on_data(self, wsapp, message):
        if message['type'] in ['sf', 'tf']: 
            token = str(message['token'])
            ltp = message['last_traded_price'] / 100.0 
            volume = message.get('volume_trade_for_the_day', 1) # Index mein volume kam aata hai, default 1
            
            if token not in self.token_to_symbol: return
            
            now = datetime.now()
            # 5-minute candle timeframe
            candle_time = now - timedelta(minutes=now.minute % 5, seconds=now.second, microseconds=now.microsecond)
            
            if self.current_candle[token] is None or self.current_candle[token]['time'] != candle_time:
                if self.current_candle[token] is not None:
                    # Candle Complete: Append and Evaluate
                    self.candles[token].append(self.current_candle[token])
                    self.evaluate_breakout_strategy(token, self.current_candle[token])
                    if len(self.candles[token]) > 50: 
                        self.candles[token].pop(0)
                
                # Start New Candle
                self.current_candle[token] = {
                    'time': candle_time, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp, 'volume': volume
                }
            else:
                # Update Current Candle
                self.current_candle[token]['high'] = max(self.current_candle[token]['high'], ltp)
                self.current_candle[token]['low'] = min(self.current_candle[token]['low'], ltp)
                self.current_candle[token]['close'] = ltp
                self.current_candle[token]['volume'] = volume

    def evaluate_breakout_strategy(self, token, candle):
        symbol = self.token_to_symbol[token]
        history = self.candles[token]
        
        if len(history) < LOOKBACK_PERIOD + 1: 
            return # Data enough nahi hai
            
        # Get past N candles (excluding the one that just closed)
        past_candles = history[-(LOOKBACK_PERIOD + 1):-1]
        
        resistance = max(c['high'] for c in past_candles)
        support = min(c['low'] for c in past_candles)
        
        avg_vol = sum(c['volume'] for c in past_candles) / LOOKBACK_PERIOD
        if avg_vol == 0: avg_vol = 1 
        
        current_vol = candle['volume']
        current_close = candle['close']
        current_high = candle['high']
        current_low = candle['low']
        
        is_high_vol = current_vol >= (avg_vol * VOLUME_MULTIPLIER)
        
        signal_type = None
        option_to_buy = None
        
        # --- 1. REAL BREAKOUT LOGIC (Sachha Breakout) ---
        if current_close > resistance and is_high_vol:
            signal_type = "🟢 REAL BREAKOUT (BUY CE)"
            option_to_buy = f"BUY {symbol} CALL (CE)"
            sl = current_low # Candle low as SL
            target = current_close + (abs(current_close - sl) * 1.5)
            
        elif current_close < support and is_high_vol:
            signal_type = "🔴 REAL BREAKDOWN (BUY PE)"
            option_to_buy = f"BUY {symbol} PUT (PE)"
            sl = current_high # Candle high as SL
            target = current_close - (abs(sl - current_close) * 1.5)

        # --- 2. FAKE BREAKOUT LOGIC (Trap / Reversal) ---
        # Price breaks resistance but closes back inside (Bearish Trap)
        elif current_high > resistance and current_close < resistance and is_high_vol:
            signal_type = "⚠️ FAKE BREAKOUT (BUY PE)"
            option_to_buy = f"BUY {symbol} PUT (PE)"
            sl = current_high # Fake breakout ki wick SL
            target = current_close - (abs(sl - current_close) * 1.5)
            
        # Price breaks support but closes back inside (Bullish Trap)
        elif current_low < support and current_close > support and is_high_vol:
            signal_type = "⚠️ FAKE BREAKDOWN (BUY CE)"
            option_to_buy = f"BUY {symbol} CALL (CE)"
            sl = current_low # Fake breakdown ki wick SL
            target = current_close + (abs(current_close - sl) * 1.5)

        if signal_type and option_to_buy:
            # Prevent multiple alerts for the same candle
            if self.last_alert_time[token] == candle['time']:
                return
            self.last_alert_time[token] = candle['time']
            
            msg = (f"🚨 <b>{signal_type}</b> 🚨\n"
                   f"Index: <b>{symbol}</b>\n\n"
                   f"Action: <b>{option_to_buy}</b>\n"
                   f"Spot Price: {current_close:.2f}\n"
                   f"Stop Loss (Spot): {sl:.2f}\n"
                   f"Target (Spot 1:1.5): {target:.2f}\n"
                   f"Volume: {current_vol/avg_vol:.1f}x (Avg)\n\n"
                   f"<i>Note: Check Option Premium before entering!</i>")
            
            logging.info(f"Signal Generated:\n{msg}")
            send_telegram_alert(msg)

    def on_error(self, wsapp, error):
        logging.error(f"WebSocket Error: {error}")

    def on_close(self, wsapp):
        logging.info("WebSocket Closed")

    def start(self):
        self.sws.on_open = self.on_open
        self.sws.on_data = self.on_data
        self.sws.on_error = self.on_error
        self.sws.on_close = self.on_close
        self.sws.connect()

if __name__ == "__main__":
    send_telegram_alert("✅ <b>ARJUN Options Bot Started</b>\nTracking Nifty & BankNifty (S&R + Volume + Fake Breakouts)...")
    obj = login_angel_one()
    if obj:
        engine = NiftyBreakoutEngine(obj)
        try:
            engine.start()
        except KeyboardInterrupt:
            send_telegram_alert("🛑 <b>ARJUN Options Bot Stopped</b>")
