import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        # Trading parameters
        self.buzz_threshold = 200
        self.take_profit_percent = 15
        self.stop_loss_percent = 8
        self.live_trading = False
        self.trading_enabled = True
        
        # Portfolio management
        self.starting_portfolio_usd = 500  # Initial capital
        self.realized_pnl = 0  # Tracks profits/losses
        self.max_open_positions = 5
        
        # AI position sizing
        self.use_ai_sizing = True
        self.min_position_usd = 20
        self.max_position_usd = 150
        
        # Market cap filters
        self.min_market_cap = 1_000_000
        self.max_market_cap = 500_000_000
        
        # Baseline
        self.baseline_hours = 168
        self.min_baseline_mentions = 10
        
        # API Keys
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.exchange_name = os.getenv("EXCHANGE_NAME", "coinbase")
        
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
    
    @property
    def total_portfolio_usd(self) -> float:
        """Dynamic portfolio = starting capital + realized profits/losses"""
        return self.starting_portfolio_usd + self.realized_pnl
    
    def add_realized_pnl(self, pnl: float):
        """Called when a trade closes"""
        self.realized_pnl += pnl
        print(f"💰 Portfolio updated: ${self.total_portfolio_usd:.2f} (P&L: {'+' if self.realized_pnl >= 0 else ''}{self.realized_pnl:.2f})")

settings = Settings()
