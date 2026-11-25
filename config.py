import os

# ===== Angel One Credentials =====
API_KEY = os.getenv('API_KEY', 'YOUR_API_KEY')
CLIENT_ID = os.getenv('CLIENT_ID', 'YOUR_CLIENT_ID')
PIN = os.getenv('PASSWORD', 'YOUR_PIN') 
TOTP_SECRET = os.getenv('TOTP_SECRET', 'YOUR_TOTP_SECRET') 

# ===== Telegram Credentials =====
TELEGRAM_BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN') 
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID', 'YOUR_CHAT_ID')       

# ===== Strategy Parameters =====
LOOKBACK_PERIOD = 20       
ATR_PERIOD = 14            
ATR_MULTIPLIER = 1.2       # SL ਨੂੰ ਥੋੜ੍ਹਾ ਘੱਟ (Tighter) ਕੀਤਾ ਗਿਆ ਹੈ 
RISK_REWARD_RATIO = 3.0    

# ===== Option Premium Settings =====
OPTION_SL_POINTS = 25      # ਆਪਸ਼ਨ ਪ੍ਰੀਮੀਅਮ ਵਿੱਚ 25 ਪੁਆਇੰਟ ਦਾ SL
OPTION_TARGET_POINTS = 40  # ਆਪਸ਼ਨ ਪ੍ਰੀਮੀਅਮ ਵਿੱਚ 40 ਪੁਆਇੰਟ ਦਾ ਟਾਰਗੇਟ

# ===== Time Filters =====
SKIP_GAP_TIME = True       
SKIP_LUNCH_CHOP = True     
EARLY_WARNING_COOLDOWN = 900 
SIGNAL_COOLDOWN = 3600     # ਸਿਗਨਲ ਸਪੈਮ ਰੋਕਣ ਲਈ 1 ਘੰਟੇ ਦਾ ਕੂਲਡਾਊਨ (3600 ਸੈਕਿੰਡ)

# ===== Indices to Track =====
INDICES_TO_TRACK = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009"
}