import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        # Trading parameters (adjustable via API)
        self.buzz_threshold = 200  # % above baseline to trigger signal
        self.take_profit_percent = 15  # Sell when up this much
        self.stop_loss_percent = 8  # Sell when down this much
        self.max_position_usd = 100  # Max $ per trade
        self.live_trading = False  # Paper trading by default
        self.trading_enabled = True  # Master switch
        
        # Baseline calculation
        self.baseline_hours = 168  # 7 days of data for baseline
        self.min_baseline_mentions = 10  # Ignore coins with very low activity
        
        # Coins to track (top 100 + memecoins)
        self.tracked_coins = [
            "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "SHIB", "DOT", 
            "LINK", "MATIC", "UNI", "ATOM", "LTC", "FIL", "APT", "ARB", "OP",
            "NEAR", "INJ", "SUI", "SEI", "TIA", "PEPE", "WIF", "BONK", "FLOKI",
            "MEME", "ORDI", "SATS", "RATS", "JTO", "JUP", "PYTH", "ONDO", "ENA",
            "W", "STRK", "MODE", "ZRO", "ZK", "BLAST", "ETHFI", "REZ", "AEVO"
        ]
        
        # API Keys (from environment)
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.exchange_name = os.getenv("EXCHANGE_NAME", "binance")  # binance, coinbase, kraken
        
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        
        self.lunarcrush_api_key = os.getenv("LUNARCRUSH_API_KEY", "")
        
        # Database
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")

settings = Settings()
