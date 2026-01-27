import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.buzz_threshold = 200
        self.take_profit_percent = 15
        self.stop_loss_percent = 8
        self.live_trading = False
        self.trading_enabled = True
        
        self.starting_portfolio_usd = 500
        self.realized_pnl = 0
        self.max_open_positions = 5
        
        self.use_ai_sizing = True
        self.min_position_usd = 20
        self.max_position_usd = 150
        
        self.min_market_cap = 1_000_000
        self.max_market_cap = 500_000_000
        
        self.min_liquidity = 50_000
        self.min_volume_24h = 100_000
        
        self.blacklisted_coins = set()
        self.cooldown_hours = 24
        self.cooldown_coins = {}
        self.max_daily_loss_usd = 100
        self.max_daily_loss_percent = 20
        self.daily_pnl = 0
        self.daily_pnl_reset_date = datetime.utcnow().date()
        
        self.last_successful_scan = None
        self.last_error = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        self.baseline_hours = 168
        self.min_baseline_mentions = 10
        
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.exchange_name = os.getenv("EXCHANGE_NAME", "coinbase")
        
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    @property
    def total_portfolio_usd(self) -> float:
        return self.starting_portfolio_usd + self.realized_pnl
    
    def add_realized_pnl(self, pnl: float):
        self.realized_pnl += pnl
        self._update_daily_pnl(pnl)
        print(f"💰 Portfolio: ${self.total_portfolio_usd:.2f}")
    
    def _update_daily_pnl(self, pnl: float):
        today = datetime.utcnow().date()
        if today != self.daily_pnl_reset_date:
            self.daily_pnl = 0
            self.daily_pnl_reset_date = today
        self.daily_pnl += pnl
    
    def is_daily_loss_limit_hit(self) -> bool:
        today = datetime.utcnow().date()
        if today != self.daily_pnl_reset_date:
            self.daily_pnl = 0
            self.daily_pnl_reset_date = today
            return False
        if self.daily_pnl <= -self.max_daily_loss_usd:
            return True
        if self.daily_pnl < 0:
            daily_loss_percent = (abs(self.daily_pnl) / self.starting_portfolio_usd) * 100
            if daily_loss_percent >= self.max_daily_loss_percent:
                return True
        return False
    
    def is_coin_blacklisted(self, coin: str) -> bool:
        return coin.upper() in self.blacklisted_coins
    
    def blacklist_coin(self, coin: str, reason: str = ""):
        self.blacklisted_coins.add(coin.upper())
        print(f"🚫 Blacklisted {coin}: {reason}")
    
    def unblacklist_coin(self, coin: str):
        self.blacklisted_coins.discard(coin.upper())
    
    def is_coin_on_cooldown(self, coin: str) -> bool:
        coin = coin.upper()
        if coin not in self.cooldown_coins:
            return False
        if datetime.utcnow() > self.cooldown_coins[coin]:
            del self.cooldown_coins[coin]
            return False
        return True
    
    def add_coin_cooldown(self, coin: str):
        coin = coin.upper()
        self.cooldown_coins[coin] = datetime.utcnow() + timedelta(hours=self.cooldown_hours)
    
    def get_cooldown_remaining(self, coin: str) -> float:
        coin = coin.upper()
        if coin not in self.cooldown_coins:
            return 0
        remaining = (self.cooldown_coins[coin] - datetime.utcnow()).total_seconds() / 3600
        return max(0, remaining)
    
    def record_successful_scan(self):
        self.last_successful_scan = datetime.utcnow()
        self.consecutive_errors = 0
    
    def record_error(self, error: str):
        self.last_error = {"error": error, "timestamp": datetime.utcnow()}
        self.consecutive_errors += 1
    
    def is_health_critical(self) -> bool:
        if self.consecutive_errors >= self.max_consecutive_errors:
            return True
        if self.last_successful_scan:
            minutes_since = (datetime.utcnow() - self.last_successful_scan).total_seconds() / 60
            if minutes_since > 10:
                return True
        return False

settings = Settings()
