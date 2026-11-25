import time
import logging
import threading
from datetime import datetime, timedelta
import pyotp
import requests
import pytz
import pandas as pd
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config import *

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
IST = pytz.timezone('Asia/Kolkata')

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200 and response.json().get('ok'):
                return True
        except Exception as e:
            logging.error(f"Telegram Error: {e}")
        time.sleep(2)
    return False

class ArjunV2Engine:
    def __init__(self):
        self.smart_obj = None
        self.sws = None
        self.jwt_token = None
        self.refresh_token = None
        self.feed_token = None
        
        self.token_to_symbol = {v: k for k, v in INDICES_TO_TRACK.items()}
        self.candles = {token: {} for token in INDICES_TO_TRACK.values()} 
        self.current_candle = {token: None for token in INDICES_TO_TRACK.values()}
        self.is_ready = {token: False for token in INDICES_TO_TRACK.values()}
        
        self.last_final_alert_time = {token: None for token in INDICES_TO_TRACK.values()}
        self.last_early_alert_time = {token: None for token in INDICES_TO_TRACK.values()} 
        self.last_tick_time = {token: None for token in INDICES_TO_TRACK.values()}
        
        self.last_signal_time_ce = {token: None for token in INDICES_TO_TRACK.values()}
        self.last_signal_time_pe = {token: None for token in INDICES_TO_TRACK.values()}

        self.token_list = [{"exchangeType": 1, "tokens": list(INDICES_TO_TRACK.values())}]
        self.scrip_master = None

    def login(self):
        try:
            self.smart_obj = SmartConnect(api_key=API_KEY)
            totp = pyotp.TOTP(TOTP_SECRET).now()
            data = self.smart_obj.generateSession(CLIENT_ID, PIN, totp)
            if data['status']:
                self.jwt_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = self.smart_obj.getfeedToken()
                logging.info("✅ Login Successful.")
                return True
        except Exception as e:
            logging.error(f"❌ Login Failed: {e}")
        return False

    def load_scrip_master(self):
        """ਆਪਸ਼ਨ ਟੋਕਨ ਲੱਭਣ ਲਈ ਸਕ੍ਰਿਪ ਮਾਸਟਰ ਡਾਊਨਲੋਡ ਅਤੇ ਸਾਫ਼ ਕਰਨਾ"""
        logging.info("📥 Downloading Scrip Master for Option Tokens...")
        try:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            df = pd.read_json(url)
            df = df[(df['name'].isin(['NIFTY', 'BANKNIFTY'])) & (df['instrumenttype'] == 'OPTIDX')].copy()
            # Angel One ਵਿੱਚ strike 100 ਨਾਲ ਗੁਣਾ ਹੁੰਦੀ ਹੈ
            df['strike_num'] = pd.to_numeric(df['strike'], errors='coerce') / 100.0
            # Expiry ਤਾਰੀਖ਼ ਨੂੰ ਸਹੀ Date ਵਿੱਚ ਬਦਲੋ
            df['expiry_dt'] = pd.to_datetime(df['expiry'], format='%d%b%Y', errors='coerce')
            self.scrip_master = df.dropna(subset=['strike_num', 'expiry_dt'])
            logging.info(f"✅ Scrip Master Loaded ({len(self.scrip_master)} contracts).")
        except Exception as e:
            logging.error(f"❌ Error loading Scrip Master: {e}")

    def get_atm_option(self, symbol, spot_price, option_type):
        """ਸਭ ਤੋਂ ਨਜ਼ਦੀਕੀ Expiry ਅਤੇ ATM Strike ਦਾ ਲਾਈਵ ਪ੍ਰੀਮੀਅਮ ਲੈਣਾ"""
        if self.scrip_master is None:
            return None, 0

        strike_round = 50 if symbol == 'NIFTY' else 100
        atm_strike = round(spot_price / strike_round) * strike_round
        today_date = pd.Timestamp(datetime.now(IST).date())

        filtered = self.scrip_master[
            (self.scrip_master['name'] == symbol) &
            (self.scrip_master['strike_num'] == float(atm_strike)) &
            (self.scrip_master['symbol'].str.endswith(option_type)) &
            (self.scrip_master['expiry_dt'] >= today_date)
        ].sort_values('expiry_dt')

        if not filtered.empty:
            row = filtered.iloc[0]
            try:
                ltp_data = self.smart_obj.ltpData("NFO", str(row['symbol']), str(row['token']))
                if ltp_data and ltp_data.get('status'):
                    return float(ltp_data['data']['ltp']), atm_strike
            except Exception as e:
                logging.error(f"LTP Fetch Error ({row['symbol']}): {e}")

        return None, atm_strike

    def fetch_historical_data(self):
        logging.info("📥 Fetching historical data...")
        now = datetime.now(IST)
        for symbol, token in INDICES_TO_TRACK.items():
            try:
                from_date = (now - timedelta(days=5)).strftime('%Y-%m-%d 09:15')
                to_date = now.strftime('%Y-%m-%d 15:30')
                param = {"exchange": "NSE", "symboltoken": token, "interval": "FIVE_MINUTE", "fromdate": from_date, "todate": to_date}
                response = self.smart_obj.getCandleData(param)
                if response and response['status'] and response['data']:
                    temp_candles = {}
                    for c in response['data']:
                        candle_dt = datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z")
                        if candle_dt + timedelta(minutes=5) <= now:
                            temp_candles[candle_dt] = {'time': candle_dt, 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4]}
                    sorted_keys = sorted(temp_candles.keys())
                    self.candles[token] = {k: temp_candles[k] for k in sorted_keys[-60:]}
                    if len(self.candles[token]) >= LOOKBACK_PERIOD + ATR_PERIOD:
                        self.is_ready[token] = True
                        logging.info(f"🟢 {symbol} READY ({len(self.candles[token])} candles)")
            except Exception as e:
                logging.error(f"❌ Data Error for {symbol}: {e}")

    def init_websocket(self):
        if self.sws:
            try: self.sws.close_connection()
            except: pass
        self.sws = SmartWebSocketV2(self.jwt_token, API_KEY, CLIENT_ID, self.feed_token)
        self.sws.on_open = self.on_open
        self.sws.on_data = self.on_data
        self.sws.on_error = self.on_error
        self.sws.on_close = self.on_close

    def on_open(self, wsapp):
        logging.info("🔌 WebSocket CONNECTED.")
        self.sws.subscribe("arjun_v2", 1, self.token_list)

    def on_error(self, wsapp, error): logging.error(f"⚠️ WS ERROR: {error}")
    def on_close(self, wsapp): logging.warning("🔌 WS DISCONNECTED.")

    def is_trade_allowed_time(self, current_time):
        t = current_time.time()
        if SKIP_GAP_TIME and t < datetime.strptime("09:30", "%H:%M").time(): return False
        if SKIP_LUNCH_CHOP and (datetime.strptime("11:30", "%H:%M").time() <= t < datetime.strptime("13:00", "%H:%M").time()): return False
        if t >= datetime.strptime("14:45", "%H:%M").time(): return False
        return True

    def on_data(self, wsapp, message):
        try:
            if 'last_traded_price' not in message: return
            token = str(message['token'])
            if token not in self.token_to_symbol: return

            exchange_ts = message.get('exchange_timestamp')
            if not exchange_ts or not isinstance(exchange_ts, (int, float)): return

            dt_object = datetime.fromtimestamp(exchange_ts / 1000.0, tz=IST)
            ltp = message['last_traded_price'] / 100.0

            candle_time = dt_object - timedelta(minutes=dt_object.minute % 5, seconds=dt_object.second, microseconds=dt_object.microsecond)

            if self.last_tick_time[token] and candle_time > self.last_tick_time[token] + timedelta(minutes=5):
                self.fetch_historical_data()
                self.current_candle[token] = None

            self.last_tick_time[token] = candle_time

            if self.current_candle[token] is None or self.current_candle[token]['time'] < candle_time:
                if self.current_candle[token] is not None:
                    closed_candle = self.current_candle[token]
                    self.candles[token][closed_candle['time']] = closed_candle
                    if self.is_trade_allowed_time(closed_candle['time']):
                        self.evaluate_final_candle(token, closed_candle)
                    if len(self.candles[token]) > 80:
                        del self.candles[token][min(self.candles[token].keys())]

                self.current_candle[token] = {'time': candle_time, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp}
            elif self.current_candle[token]['time'] == candle_time:
                self.current_candle[token]['high'] = max(self.current_candle[token]['high'], ltp)
                self.current_candle[token]['low'] = min(self.current_candle[token]['low'], ltp)
                self.current_candle[token]['close'] = ltp

            if self.is_trade_allowed_time(dt_object):
                self.check_early_breakout(token, ltp, candle_time)
        except Exception as e:
            logging.error(f"Data Error: {e}")

    def check_early_breakout(self, token, current_ltp, candle_time):
        if not self.is_ready[token]: return
        if self.last_early_alert_time[token]:
            if (datetime.now(IST) - self.last_early_alert_time[token]).total_seconds() < EARLY_WARNING_COOLDOWN: return 

        symbol = self.token_to_symbol[token]
        past_keys = [k for k in sorted(self.candles[token].keys()) if k < candle_time][-LOOKBACK_PERIOD:]
        if len(past_keys) < LOOKBACK_PERIOD: return
            
        resistance = max(self.candles[token][k]['high'] for k in past_keys)
        support = min(self.candles[token][k]['low'] for k in past_keys)
        
        if current_ltp > resistance:
            msg = f"⚠️ <b>EARLY WARNING: {symbol}</b> ⚠️\nTime: {candle_time.strftime('%H:%M')}\nCrossed Res ({resistance:.2f})\nLTP: <b>{current_ltp:.2f}</b>"
            send_telegram_alert(msg)
            self.last_early_alert_time[token] = datetime.now(IST)
        elif current_ltp < support:
            msg = f"⚠️ <b>EARLY WARNING: {symbol}</b> ⚠️\nTime: {candle_time.strftime('%H:%M')}\nCrossed Sup ({support:.2f})\nLTP: <b>{current_ltp:.2f}</b>"
            send_telegram_alert(msg)
            self.last_early_alert_time[token] = datetime.now(IST)

    def evaluate_final_candle(self, token, candle):
        if not self.is_ready[token]: return
        symbol = self.token_to_symbol[token]

        past_keys = [k for k in sorted(self.candles[token].keys()) if k < candle['time']]
        if len(past_keys) < LOOKBACK_PERIOD + ATR_PERIOD: return

        recent_candles = [self.candles[token][k] for k in past_keys[-(ATR_PERIOD + 1):]]
        tr_values = [
            max(recent_candles[i]['high'] - recent_candles[i]['low'], abs(recent_candles[i]['high'] - recent_candles[i-1]['close']), abs(recent_candles[i]['low'] - recent_candles[i-1]['close']))
            for i in range(1, len(recent_candles))
        ]
        atr = sum(tr_values) / len(tr_values) if tr_values else 0

        lookback_candles = [self.candles[token][k] for k in past_keys[-LOOKBACK_PERIOD:]]
        resistance = max(c['high'] for c in lookback_candles)
        support = min(c['low'] for c in lookback_candles)

        curr_close = candle['close']
        signal, spot_sl, option_type = None, 0, None

        if curr_close > resistance:
            signal = "🟢 CONFIRMED BREAKOUT (BUY CE)"
            spot_sl = curr_close - (atr * ATR_MULTIPLIER)
            option_type = "CE"
        elif curr_close < support:
            signal = "🔴 CONFIRMED BREAKDOWN (BUY PE)"
            spot_sl = curr_close + (atr * ATR_MULTIPLIER)
            option_type = "PE"

        if signal:
            last_time = self.last_signal_time_ce[token] if option_type == "CE" else self.last_signal_time_pe[token]
            if last_time and (datetime.now(IST) - last_time).total_seconds() < SIGNAL_COOLDOWN:
                return 

            premium, atm_strike = self.get_atm_option(symbol, curr_close, option_type)
            
            if option_type == "CE": self.last_signal_time_ce[token] = datetime.now(IST)
            else: self.last_signal_time_pe[token] = datetime.now(IST)

            self.last_final_alert_time[token] = candle['time']
            
            msg = f"🚨 <b>{signal}</b> 🚨\nIndex: <b>{symbol}</b> | Time: {candle['time'].strftime('%H:%M')}\n\n"
            msg += f"<b>--- SPOT INDEX ---</b>\nSpot Close: {curr_close:.2f}\nSpot SL: {spot_sl:.2f}\n\n"
            
            if premium:
                if symbol == 'NIFTY':
                    sl_pts, tgt_pts = NIFTY_SL_POINTS, NIFTY_TGT_POINTS
                else:
                    sl_pts, tgt_pts = BANKNIFTY_SL_POINTS, BANKNIFTY_TGT_POINTS

                opt_target = premium + tgt_pts
                
                # Expiry 'ਤੇ SL ਨੂੰ ਮਾਈਨਸ (-) ਹੋਣ ਤੋਂ ਰੋਕਣ ਲਈ max(1.0, ...) ਦੀ ਵਰਤੋਂ
                opt_sl = max(1.0, premium - sl_pts) 
                
                msg += (f"<b>--- OPTION PREMIUM ---</b>\n"
                        f"ATM Strike: {atm_strike} {option_type}\n"
                        f"Est. Premium: ₹{premium:.2f}\n"
                        f"<b>Option Target: ₹{opt_target:.2f}</b> (+{tgt_pts})\n"
                        f"<b>Option SL: ₹{opt_sl:.2f}</b> (-{sl_pts})\n\n")
            else:
                msg += f"<i>(Option premium data unavailable. Trade manually based on spot.)</i>\n\n"
                
            msg += f"<i>Note: Cooldown active for 1 hour.</i>"
            send_telegram_alert(msg)

    def market_close_monitor(self):
        while True:
            if datetime.now(IST).time() >= datetime.strptime("15:00", "%H:%M").time():
                send_telegram_alert("🔔 <b>ARJUN V2.1: Market Closed (3:00 PM). Shutting down.</b>")
                if self.sws:
                    try: self.sws.close_connection()
                    except: pass
                break
            time.sleep(30)

    def start(self):
        while not self.login(): time.sleep(10)
        
        self.load_scrip_master() 
        self.fetch_historical_data()

        threading.Thread(target=self.market_close_monitor, daemon=True).start()

        while True:
            try:
                self.init_websocket()
                self.sws.connect()
            except Exception as e:
                logging.error(f"WebSocket Crash: {e}")

            if datetime.now(IST).time() >= datetime.strptime("15:00", "%H:%M").time(): break
            time.sleep(5)
            if self.login(): self.fetch_historical_data()

if __name__ == "__main__":
    send_telegram_alert("✅ <b>ARJUN V2.1 STARTED (Premium Fix + Cooldown)</b>")
    engine = ArjunV2Engine()
    try: engine.start()
    except KeyboardInterrupt: send_telegram_alert("🛑 <b>Bot STOPPED</b>")
