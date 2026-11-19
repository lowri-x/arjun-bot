# config.py
import os

# Angel One Credentials
API_KEY = os.getenv('ANGEL_API_KEY', 'YOUR_API_KEY')
CLIENT_ID = os.getenv('ANGEL_CLIENT_ID', 'YOUR_CLIENT_ID')
PIN = os.getenv('ANGEL_PIN', 'YOUR_PIN')
TOTP_SECRET = os.getenv('ANGEL_TOTP_SECRET', 'YOUR_TOTP_SECRET')

# Telegram Credentials
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

# Strategy Parameters (Refined S&R)
LOOKBACK_PERIOD = 20      # ਪਿਛਲੇ 20 ਕੈਂਡਲ ਦੀ ਹਾਈ/ਲੋ ਦੇਖਣੀ ਹੈ
VOLUME_MULTIPLIER = 1.5   # ਵਾਲੀਅਮ ਔਸਤ ਤੋਂ 1.5 ਗੁਣਾ ਜ਼ਿਆਦਾ ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ

# Stocks to Track (ਤੁਸੀਂ ਇੱਥੇ ਆਪਣੇ ਸਟਾਕਸ ਦੇ ਨਾਮ ਅਤੇ ਟੋਕਨ ਪਾ ਸਕਦੇ ਹੋ)
# ਹੁਣੇ ਲਈ ਅਸੀਂ ਕੁਝ Nifty 50 ਸਟਾਕਸ ਦੇ ਉਦਾਹਰਨ ਲਈ ਟੋਕਨ ਦੇ ਰਹੇ ਹਾਂ
STOCKS_TO_TRACK = {
    "RELIANCE-EQ": "2885",
    "HDFCBANK-EQ": "1333",
    "TCS-EQ": "11536",
    "INFY-EQ": "1594",
    "SBIN-EQ": "3045"
}
