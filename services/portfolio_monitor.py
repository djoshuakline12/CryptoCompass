import aiohttp
import os
from datetime import datetime, timezone, timedelta
from config import settings

class PortfolioMonitor:
    """
    Monitor portfolio health and alert on issues
    """
    
    def __init__(self):
        self.starting_balance = None
        self.peak_balance = None
        self.last_alert_time = None
        self.alert_cooldown = 3600  # 1 hour between alerts
    
    async def check_health(self, sol_balance: float, usdc_balance: float, positions_value: float) -> dict:
        """
        Check portfolio health and return warnings
        """
        warnings = []
        should_pause = False
        
        total_value = usdc_balance + positions_value
        
        # Track peak
        if self.peak_balance is None:
            self.peak_balance = total_value
        else:
            self.peak_balance = max(self.peak_balance, total_value)
        
        # 1. SOL balance check (need gas)
        if sol_balance < 0.01:  # Less than ~$1.20 SOL
            warnings.append(f"⚠️ LOW GAS: {sol_balance:.4f} SOL - trades may fail!")
            should_pause = True
        elif sol_balance < 0.05:
            warnings.append(f"⚠️ Gas getting low: {sol_balance:.3f} SOL")
        
        # 2. Maximum drawdown check
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - total_value) / self.peak_balance * 100
            if drawdown >= 25:
                warnings.append(f"🛑 MAX DRAWDOWN: -{drawdown:.0f}% from peak ${self.peak_balance:.2f}")
                should_pause = True
            elif drawdown >= 15:
                warnings.append(f"⚠️ Drawdown: -{drawdown:.0f}% from peak")
        
        # 3. USDC too low to trade
        if usdc_balance < settings.min_position_usd:
            warnings.append(f"💰 Low USDC: ${usdc_balance:.2f} - can't open new positions")
        
        return {
            "healthy": len(warnings) == 0,
            "warnings": warnings,
            "should_pause_trading": should_pause,
            "total_value": total_value,
            "peak_value": self.peak_balance,
            "drawdown_percent": ((self.peak_balance - total_value) / self.peak_balance * 100) if self.peak_balance > 0 else 0
        }
    
    def get_performance_summary(self, history: list) -> dict:
        """
        Calculate performance metrics from trade history
        """
        if not history:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "profit_factor": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "avg_hold_time_hours": 0
            }
        
        wins = [t for t in history if t.get("pnl_percent", 0) > 0]
        losses = [t for t in history if t.get("pnl_percent", 0) <= 0]
        
        total_wins = sum(t.get("pnl_usd", 0) for t in wins)
        total_losses = abs(sum(t.get("pnl_usd", 0) for t in losses))
        
        return {
            "total_trades": len(history),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(history) * 100 if history else 0,
            "avg_win_percent": sum(t.get("pnl_percent", 0) for t in wins) / len(wins) if wins else 0,
            "avg_loss_percent": sum(t.get("pnl_percent", 0) for t in losses) / len(losses) if losses else 0,
            "profit_factor": total_wins / total_losses if total_losses > 0 else float('inf'),
            "total_pnl_usd": sum(t.get("pnl_usd", 0) for t in history),
            "best_trade_percent": max(t.get("pnl_percent", 0) for t in history),
            "worst_trade_percent": min(t.get("pnl_percent", 0) for t in history),
            "avg_hold_hours": sum(t.get("hold_hours", 0) for t in history) / len(history) if history else 0
        }

portfolio_monitor = PortfolioMonitor()
