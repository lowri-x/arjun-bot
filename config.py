import os

# ===== Angel One Credentials =====
API_KEY = os.getenv('ANGEL_API_KEY', 'YOUR_API_KEY')
CLIENT_ID = os.getenv('ANGEL_CLIENT_ID', 'YOUR_CLIENT_ID')
PIN = os.getenv('ANGEL_PIN', 'YOUR_PIN')
TOTP_SECRET = os.getenv('ANGEL_TOTP_SECRET', 'YOUR_TOTP_SECRET') 

# ===== Telegram Credentials =====
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

# ===== Strategy Parameters =====
LOOKBACK_PERIOD = 20       # 20 ਕੈਂਡਲਾਂ ਦਾ ਹਾਈ/ਲੋ
ATR_PERIOD = 14            # ATR ਲਈ ਪੀਰੀਅਡ
ATR_MULTIPLIER = 2.0       # SL ਲਈ 2x ATR
RISK_REWARD_RATIO = 3.0    # ਟਾਰਗੇਟ 1:3

# ===== Time Filters =====
SKIP_GAP_TIME = True       # 9:15 ਤੋਂ 9:30 ਤੱਕ ਟ੍ਰੇਡ ਨਹੀਂ
SKIP_LUNCH_CHOP = True     # 11:30 ਤੋਂ 1:00 ਤੱਕ ਟ੍ਰੇਡ ਨਹੀਂ
EARLY_WARNING_COOLDOWN = 900 # 15 ਮਿੰਟ ਦਾ ਕੂਲਡਾਊਨ (ਸੈਕਿੰਡਾਂ ਵਿੱਚ)

# ===== Indices to Track =====
INDICES_TO_TRACK = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009"
}
