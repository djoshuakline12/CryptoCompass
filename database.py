from datetime import datetime, timezone, timedelta
from config import settings
from typing import Optional

class Database:
    def __init__(self):
        self.client = None
        self._memory = {"mentions": [], "positions": [], "trades": [], "signals": []}
        
        if settings.supabase_url and settings.supabase_key:
            try:
                from supabase import create_client
                self.client = create_client(settings.supabase_url, settings.supabase_key)
                print("✅ Supabase connected")
                self._load_realized_pnl()
                self._load_open_positions()
            except Exception as e:
                print(f"❌ Supabase error: {e}")
        else:
            print("⚠️  Using in-memory storage")
    
    def _load_realized_pnl(self):
        if self.client:
            try:
                result = self.client.table("trades").select("pnl_usd").execute()
                if result.data:
                    settings.realized_pnl = sum(t.get("pnl_usd", 0) or 0 for t in result.data)
            except:
                pass
    
    def _load_open_positions(self):
        if self.client:
            try:
                result = self.client.table("positions").select("*").eq("status", "open").execute()
                if result.data:
                    self._memory["positions"] = result.data
            except:
                pass
    
    def _parse_datetime(self, dt_str: str) -> datetime:
        if not dt_str:
            return datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except:
            return datetime.now(timezone.utc)
    
    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)
    
    def _now_iso(self) -> str:
        return self._now_utc().isoformat()
    
    async def update_mention_counts(self, mentions: list[dict]):
        timestamp = self._now_iso()
        for m in mentions:
            m["timestamp"] = timestamp
        if self.client:
            try:
                for i in range(0, len(mentions), 50):
                    self.client.table("mentions").insert(mentions[i:i+50]).execute()
            except:
                pass
        self._memory["mentions"].extend(mentions)
        self._memory["mentions"] = self._memory["mentions"][-1000:]
    
    async def get_all_recent_mentions(self):
        return self._memory.get("mentions", [])[-500:]
    
    async def save_signal(self, signal: dict):
        signal["timestamp"] = self._now_iso()
        self._memory["signals"].append(signal)
        self._memory["signals"] = self._memory["signals"][-100:]
    
    async def get_active_signals(self):
        cutoff = self._now_utc() - timedelta(hours=2)
        results = []
        for s in self._memory["signals"]:
            try:
                sig_time = self._parse_datetime(s.get("timestamp", ""))
                if sig_time > cutoff:
                    results.append(s)
            except:
                pass
        return results
    
    async def open_position(self, position: dict):
        position["open_time"] = self._now_iso()
        position["status"] = "open"
        position["coin"] = position["coin"].upper()
        
        if self.client:
            try:
                self.client.table("positions").insert({
                    "coin": position["coin"],
                    "quantity": position["quantity"],
                    "buy_price": position["buy_price"],
                    "status": "open"
                }).execute()
            except:
                pass
        
        self._memory["positions"].append(position)
    
    async def get_open_positions(self):
        return [p for p in self._memory["positions"] if p.get("status") == "open"]
    
    async def has_open_position(self, coin: str):
        coin = coin.upper()
        return any(p["coin"].upper() == coin for p in await self.get_open_positions())
    
    async def close_position(self, coin: str, sell_price: float, sell_reason: str = "") -> Optional[dict]:
        coin = coin.upper()
        position = None
        
        for p in self._memory["positions"]:
            if p["coin"].upper() == coin and p.get("status") == "open":
                p["status"] = "closed"
                position = p
                break
        
        if not position:
            return None
        
        buy_price = position["buy_price"]
        quantity = position["quantity"]
        pnl_usd = (sell_price - buy_price) * quantity
        pnl_percent = ((sell_price - buy_price) / buy_price) * 100 if buy_price else 0
        
        open_time = self._parse_datetime(position.get("open_time", ""))
        now = self._now_utc()
        hold_hours = (now - open_time).total_seconds() / 3600
        
        settings.add_realized_pnl(pnl_usd)
        
        trade = {
            "coin": coin,
            "quantity": quantity,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_percent": round(pnl_percent, 2),
            "hold_hours": round(hold_hours, 2),
            "buy_time": position.get("open_time", ""),
            "sell_time": self._now_iso(),
            "sell_reason": sell_reason,
            "signal_source": position.get("signal", {}).get("source", "unknown")
        }
        
        if self.client:
            try:
                self.client.table("positions").update({"status": "closed"}).eq("coin", coin).eq("status", "open").execute()
                self.client.table("trades").insert(trade).execute()
            except:
                pass
        
        self._memory["trades"].append(trade)
        return trade
    
    async def get_trade_history(self, limit: int = 50):
        if self.client:
            try:
                result = self.client.table("trades").select("*").order("sell_time", desc=True).limit(limit).execute()
                if result.data:
                    return result.data
            except:
                pass
        return sorted(self._memory["trades"], key=lambda t: t.get("sell_time", ""), reverse=True)[:limit]
