import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.buzz_threshold = 200
        self.take_profit_percent = 15
        self.stop_loss_percent = 8
        self.live_trading = True
        self.trading_enabled = True
        
        self.starting_portfolio_usd = 19
        self.realized_pnl = 0
        self.max_open_positions = 3
        
        self.use_ai_sizing = True
        self.use_ai_smart_sell = True
        self.min_position_usd = 5
        self.max_position_usd = 19
        
        self.min_market_cap = 100_000
        self.max_market_cap = 50_000_000
        
        self.min_liquidity = 25_000
        self.min_volume_24h = 50_000
        
        self.blacklisted_coins = set()
        self.cooldown_hours = 24
        self.cooldown_coins = {}
        self.max_daily_loss_usd = 10
        self.max_daily_loss_percent = 50
        self.daily_pnl = 0
        self.daily_pnl_reset_date = datetime.now(timezone.utc).date()
        
        self.last_successful_scan = None
        self.last_error = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    @property
    def total_portfolio_usd(self) -> float:
        return self.starting_portfolio_usd + self.realized_pnl
    
    def add_realized_pnl(self, pnl: float):
        self.realized_pnl += pnl
        self._update_daily_pnl(pnl)
    
    def _update_daily_pnl(self, pnl: float):
        today = datetime.now(timezone.utc).date()
        if today != self.daily_pnl_reset_date:
            self.daily_pnl = 0
            self.daily_pnl_reset_date = today
        self.daily_pnl += pnl
    
    def is_daily_loss_limit_hit(self) -> bool:
        today = datetime.now(timezone.utc).date()
        if today != self.daily_pnl_reset_date:
            self.daily_pnl = 0
            self.daily_pnl_reset_date = today
            return False
        if self.daily_pnl <= -self.max_daily_loss_usd:
            return True
        if self.daily_pnl < 0:
            pct = (abs(self.daily_pnl) / self.starting_portfolio_usd) * 100
            if pct >= self.max_daily_loss_percent:
                return True
        return False
    
    def is_coin_blacklisted(self, coin: str) -> bool:
        return coin.upper() in self.blacklisted_coins
    
    def blacklist_coin(self, coin: str, reason: str = ""):
        self.blacklisted_coins.add(coin.upper())
    
    def unblacklist_coin(self, coin: str):
        self.blacklisted_coins.discard(coin.upper())
    
    def is_coin_on_cooldown(self, coin: str) -> bool:
        coin = coin.upper()
        if coin not in self.cooldown_coins:
            return False
        if datetime.now(timezone.utc) > self.cooldown_coins[coin]:
            del self.cooldown_coins[coin]
            return False
        return True
    
    def add_coin_cooldown(self, coin: str):
        self.cooldown_coins[coin.upper()] = datetime.now(timezone.utc) + timedelta(hours=self.cooldown_hours)
    
    def record_successful_scan(self):
        self.last_successful_scan = datetime.now(timezone.utc)
        self.consecutive_errors = 0
    
    def record_error(self, error: str):
        self.last_error = {"error": error, "timestamp": datetime.now(timezone.utc).isoformat()}
        self.consecutive_errors += 1
    
    def is_health_critical(self) -> bool:
        if self.consecutive_errors >= self.max_consecutive_errors:
            return True
        if self.last_successful_scan:
            mins = (datetime.now(timezone.utc) - self.last_successful_scan).total_seconds() / 60
            if mins > 10:
                return True
        return False

settings = Settings()
