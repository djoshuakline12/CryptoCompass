import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.buzz_threshold = 200
        
        # Exit targets
        self.take_profit_percent = 8
        self.stop_loss_percent = 5
        
        self.live_trading = True
        self.trading_enabled = True
        
        self.starting_portfolio_usd = 6
        self.realized_pnl = 0
        self.max_open_positions = 3
        
        self.use_ai_sizing = True
        self.use_ai_smart_sell = True
        self.min_position_usd = 1
        self.max_position_usd = 3
        
        # === TIER 1: SAFE TRADES (80% of portfolio) ===
        self.min_market_cap = 500_000
        self.max_market_cap = 50_000_000
        self.min_liquidity = 100_000
        self.min_volume_24h = 50_000
        
        # === TIER 2: DEGEN PLAYS - Pump.fun (20% of portfolio max) ===
        self.degen_enabled = True
        self.degen_max_portfolio_percent = 20  # Max 20% in degen plays
        self.degen_max_position_usd = 1.5      # Smaller positions
        self.degen_min_market_cap = 5_000      # $5k minimum (very early)
        self.degen_max_market_cap = 100_000    # $100k max (still early)
        self.degen_take_profit = 25            # Higher target (more volatile)
        self.degen_stop_loss = 15              # Wider stop (more volatile)
        
        self.blacklisted_coins = set([
            "SOL", "ETH", "BTC", "USDC", "USDT", "HYPE", "BONK", "WIF",
            "JUP", "RAY", "ORCA", "PYTH", "JTO", "MOBILE", "RENDER"
        ])
        
        self.cooldown_hours = 48
        self.cooldown_coins = {}
        self.max_daily_loss_usd = 2
        self.max_daily_loss_percent = 30
        self.daily_pnl = 0
        self.daily_pnl_reset_date = datetime.now(timezone.utc).date()
        
        self.last_successful_scan = None
        self.last_error = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        self.estimated_fee_percent = 1.0
        
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")
        self.exchange_api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    @property
    def total_portfolio_usd(self) -> float:
        return self.starting_portfolio_usd + self.realized_pnl
    
    def get_degen_budget(self, current_portfolio: float, degen_positions_value: float) -> float:
        """Calculate remaining budget for degen plays"""
        max_degen = current_portfolio * (self.degen_max_portfolio_percent / 100)
        remaining = max_degen - degen_positions_value
        return max(0, remaining)
    
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
        return self.daily_pnl <= -self.max_daily_loss_usd
    
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
        return self.consecutive_errors >= self.max_consecutive_errors

settings = Settings()
