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
ATR_MULTIPLIER = 1.2       
RISK_REWARD_RATIO = 3.0    

# ===== Option Premium Settings =====
# NIFTY ਲਈ SL/ਟਾਰਗੇਟ
NIFTY_SL_POINTS = 25      
NIFTY_TGT_POINTS = 40  

# BANKNIFTY ਲਈ SL/ਟਾਰਗੇਟ (ਵੱਧ ਪ੍ਰੀਮੀਅਮ ਕਾਰਨ ਥੋੜ੍ਹੇ ਵੱਡੇ)
BANKNIFTY_SL_POINTS = 60  
BANKNIFTY_TGT_POINTS = 90 

# ===== Time Filters =====
SKIP_GAP_TIME = True       
SKIP_LUNCH_CHOP = True     
EARLY_WARNING_COOLDOWN = 900 
SIGNAL_COOLDOWN = 3600     # ਸਿਗਨਲ ਸਪੈਮ ਰੋਕਣ ਲਈ 1 ਘੰਟੇ ਦਾ ਕੂਲਡਾਊਨ

# ===== Indices to Track =====
INDICES_TO_TRACK = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009"
}
