from datetime import datetime, timedelta
from config import settings
from typing import Optional

class Database:
    def __init__(self):
        self.client = None
        self._memory = {
            "mentions": [],
            "positions": [],
            "trades": [],
            "signals": []
        }
        
        if settings.supabase_url and settings.supabase_key:
            try:
                from supabase import create_client
                self.client = create_client(settings.supabase_url, settings.supabase_key)
                print("✅ Supabase connected")
                self._load_realized_pnl()
                self._load_open_positions()
            except Exception as e:
                print(f"❌ Supabase error: {e}")
                self.client = None
        else:
            print("⚠️  Using in-memory storage")
    
    def _load_realized_pnl(self):
        if self.client:
            try:
                result = self.client.table("trades").select("pnl_usd").execute()
                if result.data:
                    total_pnl = sum(t.get("pnl_usd", 0) or 0 for t in result.data)
                    settings.realized_pnl = total_pnl
                    print(f"💰 Loaded historical P&L: ${total_pnl:.2f}")
            except Exception as e:
                print(f"Error loading P&L: {e}")
    
    def _load_open_positions(self):
        if self.client:
            try:
                result = self.client.table("positions").select("*").eq("status", "open").execute()
                if result.data:
                    self._memory["positions"] = result.data
                    print(f"📊 Loaded {len(result.data)} open positions")
            except Exception as e:
                print(f"Error loading positions: {e}")
    
    async def update_mention_counts(self, mentions: list[dict]):
        timestamp = datetime.utcnow().isoformat()
        for mention in mentions:
            mention["timestamp"] = timestamp
        
        if self.client:
            try:
                batch_size = 50
                for i in range(0, len(mentions), batch_size):
                    batch = mentions[i:i+batch_size]
                    self.client.table("mentions").insert(batch).execute()
            except Exception as e:
                print(f"DB insert error: {e}")
        
        self._memory["mentions"].extend(mentions)
        self._memory["mentions"] = self._memory["mentions"][-1000:]
    
    async def get_all_recent_mentions(self) -> list[dict]:
        return self._memory.get("mentions", [])[-500:]
    
    async def get_baseline(self, coin: str) -> float:
        mentions = [m for m in self._memory["mentions"] if m.get("coin") == coin]
        if not mentions:
            return 0
        return sum(m.get("count", 0) for m in mentions) / max(len(mentions), 1)
    
    async def get_recent_mentions(self, coin: str, hours: int = 1) -> int:
        mentions = [m for m in self._memory["mentions"] if m.get("coin") == coin]
        return sum(m.get("count", 0) for m in mentions)
    
    async def save_signal(self, signal: dict):
        signal["timestamp"] = datetime.utcnow().isoformat()
        
        if self.client:
            try:
                db_signal = {
                    "coin": signal.get("coin"),
                    "current_mentions": signal.get("current_mentions"),
                    "baseline_mentions": signal.get("baseline_mentions"),
                    "percent_above_baseline": signal.get("percent_above_baseline")
                }
                self.client.table("signals").insert(db_signal).execute()
            except Exception as e:
                print(f"DB signal error: {e}")
        
        self._memory["signals"].append(signal)
        self._memory["signals"] = self._memory["signals"][-100:]
    
    async def get_active_signals(self) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(hours=2)
        return [s for s in self._memory["signals"] if datetime.fromisoformat(s["timestamp"]) > cutoff]
    
    async def open_position(self, position: dict):
        position["open_time"] = datetime.utcnow().isoformat()
        position["status"] = "open"
        position["coin"] = position["coin"].upper()
        
        if self.client:
            try:
                db_pos = {
                    "coin": position.get("coin"),
                    "quantity": position.get("quantity"),
                    "buy_price": position.get("buy_price"),
                    "status": "open"
                }
                self.client.table("positions").insert(db_pos).execute()
            except Exception as e:
                print(f"DB position error: {e}")
        
        self._memory["positions"].append(position)
        print(f"📝 Opened position: {position['coin']}")
    
    async def get_open_positions(self) -> list[dict]:
        return [p for p in self._memory["positions"] if p.get("status") == "open"]
    
    async def has_open_position(self, coin: str) -> bool:
        coin = coin.upper()
        positions = await self.get_open_positions()
        return any(p["coin"].upper() == coin for p in positions)
    
    async def close_position(self, coin: str, sell_price: float, sell_reason: str = "") -> Optional[dict]:
        coin = coin.upper()
        position = None
        
        for p in self._memory["positions"]:
            if p["coin"].upper() == coin and p.get("status") == "open":
                p["status"] = "closed"
                position = p
                break
        
        if not position:
            print(f"⚠️ No open position found for {coin}")
            return None
        
        buy_price = position["buy_price"]
        quantity = position["quantity"]
        pnl_usd = (sell_price - buy_price) * quantity
        pnl_percent = ((sell_price - buy_price) / buy_price) * 100 if buy_price else 0
        open_time = datetime.fromisoformat(position["open_time"])
        hold_hours = (datetime.utcnow() - open_time).total_seconds() / 3600
        
        settings.add_realized_pnl(pnl_usd)
        
        trade = {
            "coin": coin,
            "quantity": quantity,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_percent": round(pnl_percent, 2),
            "hold_hours": round(hold_hours, 2),
            "buy_time": position["open_time"],
            "sell_time": datetime.utcnow().isoformat(),
            "sell_reason": sell_reason,
            "risk_score": position.get("risk_score", 0),
            "signal_source": position.get("signal", {}).get("source", "unknown")
        }
        
        if self.client:
            try:
                self.client.table("positions").update({"status": "closed"}).eq("coin", coin).eq("status", "open").execute()
                self.client.table("trades").insert(trade).execute()
            except Exception as e:
                print(f"DB close position error: {e}")
        
        self._memory["trades"].append(trade)
        print(f"📝 Closed position: {coin} | PnL: {pnl_percent:+.1f}%")
        return trade
    
    async def get_trade_history(self, limit: int = 50) -> list[dict]:
        if self.client:
            try:
                result = self.client.table("trades").select("*").order("sell_time", desc=True).limit(limit).execute()
                if result.data:
                    return result.data
            except Exception as e:
                print(f"DB get trades error: {e}")
        
        return sorted(self._memory["trades"], key=lambda t: t.get("sell_time", ""), reverse=True)[:limit]
