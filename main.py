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

    def _fetch_yahoo_chg(self, ticker):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            meta = data['chart']['result'][0]['meta']

            price = meta['regularMarketPrice']
            prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')

            if prev_close is None:
                return price, 0.0

            chg_pct = ((price - prev_close) / prev_close) * 100
            return price, chg_pct
        except Exception as e:
            logging.error(f"Error fetching {ticker}: {e}")
            return None, None

    def send_morning_mood_summary(self):
        now_str = datetime.now(IST).strftime("%d %b %Y • %I:%M %p")
        score = 0
        global_lines = []

        vix_block = "⚪ <b>India VIX:</b> <i>Unavailable</i>"
        try:
            vix_res = self.smart_obj.ltpData("NSE", "INDIA VIX", "99926017")
            if vix_res and vix_res.get("status"):
                vix = float(vix_res["data"]["ltp"])
                if vix < 14:
                    vix_badge, vix_bar, vix_tip = "🟢 CALM", "🟩⬜⬜⬜⬜", "Slow moves, avoid wide targets"
                elif vix <= 22:
                    vix_badge, vix_bar, vix_tip = "🟡 OPTIMAL", "🟨🟨🟨⬜⬜", "Healthy trend &amp; momentum"
                else:
                    vix_badge, vix_bar, vix_tip = "🔴 HIGH RISK", "🟥🟥🟥🟥🟥", "Sharp spikes, tighten qty"

                vix_block = (
                    f"⚡ <b>India VIX:</b> <code>{vix:.2f}</code> {vix_badge}\n"
                    f" {vix_bar} <i>({vix_tip})</i>"
                )
        except Exception:
            pass

        assets = [
            ("🇺🇸 S&amp;P 500", "^GSPC", False),
            ("💻 Nasdaq", "^IXIC", False),
            ("🛢️ Brent Crude", "BZ=F", True),
            ("💵 USD / INR", "INR=X", True),
        ]

        for label, ticker, invert in assets:
            price, chg = self._fetch_yahoo_chg(ticker)
            if price is not None:
                is_good = (chg <= 0) if invert else (chg >= 0)
                dot = "🟢" if is_good else "🔴"
                arrow = "📈" if chg >= 0 else "📉"
                score += 1 if is_good else -1
                global_lines.append(
                    f"{dot} <b>{label}:</b> <code>{price:,.2f}</code> {arrow} <b>{chg:+.2f}%</b>"
                )

        if score >= 2:
            mood_text = "🟢 <b>BULLISH BIAS</b> <code>[🟩🟩🟩🟩⬜]</code>"
        elif score <= -2:
            mood_text = "🔴 <b>BEARISH BIAS</b> <code>[🟥🟥🟥🟥⬜]</code>"
        else:
            mood_text = "🟡 <b>MIXED / NEUTRAL</b> <code>[🟨🟨🟨⬜⬜]</code>"

        global_section = "\n".join(global_lines) if global_lines else "⚪ <i>Global data unavailable</i>"

        msg = (
            f"🌅 <b>ARJUN V2.1 • PRE-MARKET PULSE</b>\n"
            f"📅 <i>{now_str} IST</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧭 <b>Market Mood:</b> {mood_text}\n\n"
            f"📊 <b>VOLATILITY RADAR</b>\n"
            f"{vix_block}\n\n"
            f"🌍 <b>GLOBAL &amp; MACRO CUES</b>\n"
            f"{global_section}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Active Guardrails:</b>\n"
            f"• ⏳ Gap Skip: <code>09:15–09:30</code> | Chop Skip: <code>11:30–13:00</code>\n"
            f"• 🎯 NIFTY: <code>SL -25 / TGT +40</code> | BNF: <code>SL -60 / TGT +90</code>\n"
            f"🚀 <i>Live signals begin at 09:30 AM IST.</i>"
        )
        send_telegram_alert(msg)

    def load_scrip_master(self):
        logging.info("📥 Downloading Scrip Master for Option Tokens...")
        try:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            df = pd.read_json(url)
            df = df[(df['name'].isin(['NIFTY', 'BANKNIFTY'])) & (df['instrumenttype'] == 'OPTIDX')].copy()
            df['strike_num'] = pd.to_numeric(df['strike'], errors='coerce') / 100.0
            df['expiry_dt'] = pd.to_datetime(df['expiry'], format='%d%b%Y', errors='coerce')
            self.scrip_master = df.dropna(subset=['strike_num', 'expiry_dt'])
            logging.info(f"✅ Scrip Master Loaded ({len(self.scrip_master)} contracts).")
        except Exception as e:
            logging.error(f"❌ Error loading Scrip Master: {e}")

    def get_atm_option(self, symbol, spot_price, option_type):
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
            try:
                self.sws.close_connection()
            except Exception:
                pass
        self.sws = SmartWebSocketV2(self.jwt_token, API_KEY, CLIENT_ID, self.feed_token)
        self.sws.on_open = self.on_open
        self.sws.on_data = self.on_data
        self.sws.on_error = self.on_error
        self.sws.on_close = self.on_close

    def on_open(self, wsapp):
        logging.info("🔌 WebSocket CONNECTED.")
        self.sws.subscribe("arjun_v2", 1, self.token_list)

    def on_error(self, wsapp, error):
        logging.error(f"⚠️ WS ERROR: {error}")

    def on_close(self, wsapp):
        logging.warning("🔌 WS DISCONNECTED.")

    def is_trade_allowed_time(self, current_time):
        t = current_time.time()
        if SKIP_GAP_TIME and t < datetime.strptime("09:30", "%H:%M").time():
            return False
        if SKIP_LUNCH_CHOP and (datetime.strptime("11:30", "%H:%M").time() <= t < datetime.strptime("13:00", "%H:%M").time()):
            return False
        if t >= datetime.strptime("14:45", "%H:%M").time():
            return False
        return True

    def on_data(self, wsapp, message):
        try:
            if 'last_traded_price' not in message:
                return
            token = str(message['token'])
            if token not in self.token_to_symbol:
                return

            exchange_ts = message.get('exchange_timestamp')
            if not exchange_ts or not isinstance(exchange_ts, (int, float)):
                return

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
        if not self.is_ready[token]:
            return
        if self.last_early_alert_time[token]:
            if (datetime.now(IST) - self.last_early_alert_time[token]).total_seconds() < EARLY_WARNING_COOLDOWN:
                return

        symbol = self.token_to_symbol[token]
        past_keys = [k for k in sorted(self.candles[token].keys()) if k < candle_time][-LOOKBACK_PERIOD:]
        if len(past_keys) < LOOKBACK_PERIOD:
            return

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

    def calculate_ema(self, candles_list, period=20):
        closes = [c['close'] for c in candles_list]
        if len(closes) < period:
            return sum(closes) / len(closes) if closes else 0

        multiplier = 2 / (period + 1)
        sma = sum(closes[:period]) / period
        ema = sma
        for close in closes[period:]:
            ema = (close - ema) * multiplier + ema
        return ema

    def check_confirmation(self, candles_list, current_candle, option_type):
        c_range = current_candle['high'] - current_candle['low']
        if c_range <= 0:
            return False, 0.0, "NONE"

        body = abs(current_candle['close'] - current_candle['open'])
        body_ratio = body / c_range

        if body_ratio < 0.35:
            return False, 0.0, "DOJI"

        if option_type == "CE" and current_candle['close'] <= current_candle['open']:
            return False, 0.0, "WRONG_COLOR"
        if option_type == "PE" and current_candle['close'] >= current_candle['open']:
            return False, 0.0, "WRONG_COLOR"

        closes = [c['close'] for c in candles_list] + [current_candle['close']]
        if len(closes) < 15:
            return True, 50.0, "B+"

        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0.0))
            losses.append(abs(min(diff, 0.0)))

        avg_gain = sum(gains[:14]) / 14.0
        avg_loss = sum(losses[:14]) / 14.0
        for i in range(14, len(gains)):
            avg_gain = (avg_gain * 13 + gains[i]) / 14.0
            avg_loss = (avg_loss * 13 + losses[i]) / 14.0

        rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

        if option_type == "CE" and (52.0 <= rsi <= 78.0):
            grade = "🔥 A+" if body_ratio >= 0.55 else "✅ B+"
            return True, rsi, grade
        if option_type == "PE" and (22.0 <= rsi <= 48.0):
            grade = "🔥 A+" if body_ratio >= 0.55 else "✅ B+"
            return True, rsi, grade

        return False, rsi, "RSI_OUT"

    def evaluate_final_candle(self, token, candle):
        if not self.is_ready[token]:
            return
        symbol = self.token_to_symbol[token]

        past_keys = [k for k in sorted(self.candles[token].keys()) if k < candle['time']]
        if len(past_keys) < LOOKBACK_PERIOD + ATR_PERIOD:
            return

        all_past_candles = [self.candles[token][k] for k in past_keys]

        recent_candles = all_past_candles[-(ATR_PERIOD + 1):]
        tr_values = [
            max(recent_candles[i]['high'] - recent_candles[i]['low'], abs(recent_candles[i]['high'] - recent_candles[i - 1]['close']), abs(recent_candles[i]['low'] - recent_candles[i - 1]['close']))
            for i in range(1, len(recent_candles))
        ]
        atr = sum(tr_values) / len(tr_values) if tr_values else 0

        lookback_candles = all_past_candles[-LOOKBACK_PERIOD:]
        resistance = max(c['high'] for c in lookback_candles)
        support = min(c['low'] for c in lookback_candles)

        ema20 = self.calculate_ema(all_past_candles, 20)

        curr_close = candle['close']
        signal, spot_sl, option_type = None, 0, None

        if curr_close > resistance and curr_close > ema20:
            signal = "🟢 GREEN BUY CALL (CE) 🟢"
            spot_sl = curr_close - (atr * ATR_MULTIPLIER)
            option_type = "CE"
        elif curr_close < support and curr_close < ema20:
            signal = "🔴 RED BUY PUT (PE) 🔴"
            spot_sl = curr_close + (atr * ATR_MULTIPLIER)
            option_type = "PE"

        if signal:
            # 1. Normal Confirmation (Body, RSI)
            is_confirmed, rsi_val, grade = self.check_confirmation(all_past_candles, candle, option_type)
            if not is_confirmed:
                logging.info(f"🚫 {symbol} {option_type} skipped ({grade}, RSI={rsi_val:.1f})")
                return

            # 2. CRT Liquidity Sweep Check (FIXED)
            crt_confirmed = False
            for i in range(1, min(7, len(all_past_candles) - LOOKBACK_PERIOD)):
                sweep_candle = all_past_candles[-i]
                prior_box = all_past_candles[-(LOOKBACK_PERIOD + i):-i]
                
                prior_res = max(c['high'] for c in prior_box)
                prior_sup = min(c['low'] for c in prior_box)

                if option_type == "CE" and sweep_candle['low'] < prior_sup and sweep_candle['close'] > prior_sup:
                    crt_confirmed = True
                    break
                if option_type == "PE" and sweep_candle['high'] > prior_res and sweep_candle['close'] < prior_res:
                    crt_confirmed = True
                    break

            if crt_confirmed:
                grade = "🔥 A+ (CRT Sweep)"
                logging.info(f"✅ CRT Liquidity Sweep Confirmed for {symbol}.")

            # 3. Cooldown Check
            last_time = self.last_signal_time_ce[token] if option_type == "CE" else self.last_signal_time_pe[token]
            if last_time and (datetime.now(IST) - last_time).total_seconds() < SIGNAL_COOLDOWN:
                return

            premium, atm_strike = self.get_atm_option(symbol, curr_close, option_type)

            if option_type == "CE":
                self.last_signal_time_ce[token] = datetime.now(IST)
            else:
                self.last_signal_time_pe[token] = datetime.now(IST)

            self.last_final_alert_time[token] = candle['time']

            # ✅ FIX: ਇਹ ਲਾਈਨ ਪੂਰੀ ਕਰ ਦਿੱਤੀ ਗਈ ਹੈ
            msg = f"🚨 <b>{signal}</b> 🚨\nIndex: <b>{symbol}</b> | Time: {candle['time'].strftime('%H:%M')}\n"
            msg += f"<b>Quality:</b> {grade} | <b>RSI:</b> {rsi_val:.1f}\n\n"
            msg += f"<b>--- SPOT INDEX ---</b>\nS