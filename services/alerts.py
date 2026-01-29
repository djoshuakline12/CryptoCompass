import aiohttp
import os
from datetime import datetime, timezone

class AlertService:
    def __init__(self):
        self.discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    async def send_alert(self, message: str, alert_type: str = "info"):
        if not self.discord_webhook:
            return
        emoji = {"buy": "🟢", "sell": "🔴", "profit": "💰", "loss": "📉", "warning": "⚠️"}.get(alert_type, "📢")
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.discord_webhook, json={"content": f"{emoji} {message}"}, timeout=aiohttp.ClientTimeout(total=5))
        except:
            pass
    
    async def alert_buy(self, coin: str, amount: float, price: float, reason: str = ""):
        await self.send_alert(f"BUY {coin} ${amount:.2f} @ ${price:.8f} | {reason}", "buy")
    
    async def alert_sell(self, coin: str, pnl_percent: float, pnl_usd: float, reason: str = ""):
        await self.send_alert(f"SELL {coin} {pnl_percent:+.1f}% (${pnl_usd:+.2f}) | {reason}", "profit" if pnl_percent > 0 else "loss")
    
    async def alert_warning(self, message: str):
        await self.send_alert(message, "warning")

alert_service = AlertService()
