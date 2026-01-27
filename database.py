from supabase import create_client, Client
from datetime import datetime, timedelta
from config import settings
from typing import Optional
import json

class Database:
    def __init__(self):
        if settings.supabase_url and settings.supabase_key:
            self.client: Client = create_client(settings.supabase_url, settings.supabase_key)
        else:
            self.client = None
            print("⚠️  Supabase not configured - using in-memory storage")
            self._memory = {
                "mentions": [],
                "positions": [],
                "trades": [],
                "signals": []
            }
    
    async def update_mention_counts(self, mentions: list[dict]):
        """Store mention counts with timestamp"""
        timestamp = datetime.utcnow().isoformat()
        
        for mention in mentions:
            mention["timestamp"] = timestamp
        
        if self.client:
            self.client.table("mentions").insert(mentions).execute()
        else:
            self._memory["mentions"].extend(mentions)
            # Keep only last 7 days in memory
            cutoff = datetime.utcnow() - timedelta(days=7)
            self._memory["mentions"] = [
                m for m in self._memory["mentions"] 
                if datetime.fromisoformat(m["timestamp"]) > cutoff
            ]
    
    async def get_baseline(self, coin: str) -> float:
        """Get average hourly mentions over baseline period"""
        cutoff = datetime.utcnow() - timedelta(hours=settings.baseline_hours)
        
        if self.client:
            result = self.client.table("mentions")\
                .select("count")\
                .eq("coin", coin)\
                .gte("timestamp", cutoff.isoformat())\
                .execute()
            
            if not result.data:
                return 0
            
            total = sum(r["count"] for r in result.data)
            hours = settings.baseline_hours
            return total / hours
        else:
            mentions = [
                m for m in self._memory["mentions"]
                if m["coin"] == coin and datetime.fromisoformat(m["timestamp"]) > cutoff
            ]
            if not mentions:
                return 0
            total = sum(m["count"] for m in mentions)
            return total / settings.baseline_hours
    
    async def get_recent_mentions(self, coin: str, hours: int = 1) -> int:
        """Get mention count in the last N hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        if self.client:
            result = self.client.table("mentions")\
                .select("count")\
                .eq("coin", coin)\
                .gte("timestamp", cutoff.isoformat())\
                .execute()
            
            return sum(r["count"] for r in result.data) if result.data else 0
        else:
            mentions = [
                m for m in self._memory["mentions"]
                if m["coin"] == coin and datetime.fromisoformat(m["timestamp"]) > cutoff
            ]
            return sum(m["count"] for m in mentions)
    
    async def save_signal(self, signal: dict):
        """Record a detected signal"""
        signal["timestamp"] = datetime.utcnow().isoformat()
        
        if self.client:
            self.client.table("signals").insert(signal).execute()
        else:
            self._memory["signals"].append(signal)
    
    async def get_active_signals(self) -> list[dict]:
        """Get signals from the last 2 hours"""
        cutoff = datetime.utcnow() - timedelta(hours=2)
        
        if self.client:
            result = self.client.table("signals")\
                .select("*")\
                .gte("timestamp", cutoff.isoformat())\
                .order("timestamp", desc=True)\
                .execute()
            return result.data or []
        else:
            return [
                s for s in self._memory["signals"]
                if datetime.fromisoformat(s["timestamp"]) > cutoff
            ]
    
    async def open_position(self, position: dict):
        """Record a new position"""
        position["open_time"] = datetime.utcnow().isoformat()
        position["status"] = "open"
        
        if self.client:
            self.client.table("positions").insert(position).execute()
        else:
            self._memory["positions"].append(position)
    
    async def get_open_positions(self) -> list[dict]:
        """Get all open positions"""
        if self.client:
            result = self.client.table("positions")\
                .select("*")\
                .eq("status", "open")\
                .execute()
            return result.data or []
        else:
            return [p for p in self._memory["positions"] if p.get("status") == "open"]
    
    async def close_position(self, coin: str, sell_price: float):
        """Close a position and record the trade"""
        positions = await self.get_open_positions()
        position = next((p for p in positions if p["coin"] == coin), None)
        
        if not position:
            return None
        
        # Calculate trade results
        buy_price = position["buy_price"]
        quantity = position["quantity"]
        pnl_usd = (sell_price - buy_price) * quantity
        pnl_percent = ((sell_price - buy_price) / buy_price) * 100
        
        open_time = datetime.fromisoformat(position["open_time"])
        hold_hours = (datetime.utcnow() - open_time).total_seconds() / 3600
        
        trade = {
            "coin": coin,
            "quantity": quantity,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_percent": round(pnl_percent, 2),
            "hold_hours": round(hold_hours, 2),
            "buy_time": position["open_time"],
            "sell_time": datetime.utcnow().isoformat()
        }
        
        if self.client:
            # Update position status
            self.client.table("positions")\
                .update({"status": "closed"})\
                .eq("coin", coin)\
                .eq("status", "open")\
                .execute()
            
            # Record trade
            self.client.table("trades").insert(trade).execute()
        else:
            for p in self._memory["positions"]:
                if p["coin"] == coin and p.get("status") == "open":
                    p["status"] = "closed"
            self._memory["trades"].append(trade)
        
        return trade
    
    async def get_trade_history(self, limit: int = 50) -> list[dict]:
        """Get completed trades"""
        if self.client:
            result = self.client.table("trades")\
                .select("*")\
                .order("sell_time", desc=True)\
                .limit(limit)\
                .execute()
            return result.data or []
        else:
            return sorted(
                self._memory["trades"],
                key=lambda t: t["sell_time"],
                reverse=True
            )[:limit]
    
    async def has_open_position(self, coin: str) -> bool:
        """Check if we already have an open position for this coin"""
        positions = await self.get_open_positions()
        return any(p["coin"] == coin for p in positions)
