from datetime import datetime, timedelta
from config import settings
from typing import Optional

class Database:
    def __init__(self):
        self.client = None
        print("⚠️  Using in-memory storage")
        self._memory = {
            "mentions": [],
            "positions": [],
            "trades": [],
            "signals": []
        }
    
    async def update_mention_counts(self, mentions: list[dict]):
        timestamp = datetime.utcnow().isoformat()
        for mention in mentions:
            mention["timestamp"] = timestamp
        self._memory["mentions"].extend(mentions)
        # Keep only last 1000
        self._memory["mentions"] = self._memory["mentions"][-1000:]
    
    async def get_all_recent_mentions(self) -> list[dict]:
        return self._memory.get("mentions", [])[-500:]
    
    async def get_baseline(self, coin: str) -> float:
        cutoff = datetime.utcnow() - timedelta(hours=settings.baseline_hours)
        mentions = [m for m in self._memory["mentions"] if m.get("coin") == coin]
        if not mentions:
            return 0
        return sum(m.get("count", 0) for m in mentions) / max(len(mentions), 1)
    
    async def get_recent_mentions(self, coin: str, hours: int = 1) -> int:
        mentions = [m for m in self._memory["mentions"] if m.get("coin") == coin]
        return sum(m.get("count", 0) for m in mentions)
    
    async def save_signal(self, signal: dict):
        signal["timestamp"] = datetime.utcnow().isoformat()
        self._memory["signals"].append(signal)
        self._memory["signals"] = self._memory["signals"][-100:]
    
    async def get_active_signals(self) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(hours=2)
        return [s for s in self._memory["signals"] if datetime.fromisoformat(s["timestamp"]) > cutoff]
    
    async def open_position(self, position: dict):
        position["open_time"] = datetime.utcnow().isoformat()
        position["status"] = "open"
        self._memory["positions"].append(position)
    
    async def get_open_positions(self) -> list[dict]:
        return [p for p in self._memory["positions"] if p.get("status") == "open"]
    
    async def has_open_position(self, coin: str) -> bool:
        return any(p["coin"] == coin and p.get("status") == "open" for p in self._memory["positions"])
    
    async def close_position(self, coin: str, sell_price: float):
        for p in self._memory["positions"]:
            if p["coin"] == coin and p.get("status") == "open":
                p["status"] = "closed"
                
                buy_price = p["buy_price"]
                quantity = p["quantity"]
                pnl_usd = (sell_price - buy_price) * quantity
                pnl_percent = ((sell_price - buy_price) / buy_price) * 100
                open_time = datetime.fromisoformat(p["open_time"])
                hold_hours = (datetime.utcnow() - open_time).total_seconds() / 3600
                
                trade = {
                    "coin": coin,
                    "quantity": quantity,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "pnl_usd": round(pnl_usd, 2),
                    "pnl_percent": round(pnl_percent, 2),
                    "hold_hours": round(hold_hours, 2),
                    "buy_time": p["open_time"],
                    "sell_time": datetime.utcnow().isoformat()
                }
                self._memory["trades"].append(trade)
                return trade
        return None
    
    async def get_trade_history(self, limit: int = 50) -> list[dict]:
        return sorted(self._memory["trades"], key=lambda t: t.get("sell_time", ""), reverse=True)[:limit]
