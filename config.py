import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        # Trading parameters
        self.buzz_threshold = 200
        self.take_profit_percent = 15
        self.stop_loss_percent = 8
        self.max_position_usd = 100
        self.live_trading = False
        self.trading_enabled = True
        
        # Market cap filters (in USD)
        self.min_market_cap = 1_000_000      # $1M minimum
        self.max_market_cap = 500_000_000    # $500M maximum
        
        # Baseline calculation
        self.baseline_hours = 168
        self.min_baseline_mentions = 10
        
        # Tracked coins - now dynamically filtered
        self.tracked_coins = []
        
        # API Keys
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.exchange_name = os.getenv("EXCHANGE_NAME", "binance")
        
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self.lunarcrush_api_key = os.getenv("LUNARCRUSH_API_KEY", "")
        
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")

settings = Settings()
