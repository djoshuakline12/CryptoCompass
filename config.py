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
        
        # Position limits
        self.max_open_positions = 5  # Configurable
        self.total_portfolio_usd = 500  # Total amount in circulation
        
        # AI position sizing
        self.use_ai_sizing = True  # Enable smart allocation
        self.min_position_usd = 20  # Minimum per trade
        self.max_position_usd = 150  # Maximum per trade
        
        # Market cap filters
        self.min_market_cap = 1_000_000
        self.max_market_cap = 500_000_000
        
        # Baseline calculation
        self.baseline_hours = 168
        self.min_baseline_mentions = 10
        
        # API Keys
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.exchange_name = os.getenv("EXCHANGE_NAME", "coinbase")
        
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")

settings = Settings()
