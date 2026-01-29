import aiohttp
import os
from datetime import datetime, timezone, timedelta

class WhaleTracker:
    def __init__(self):
        self.recent_whale_buys = {}
        self.last_scan = None
    
    async def scan_whale_activity(self) -> dict:
        if self.last_scan and (datetime.now(timezone.utc) - self.last_scan).seconds < 120:
            return self.recent_whale_buys
        self.last_scan = datetime.now(timezone.utc)
        return self.recent_whale_buys
    
    def get_whale_score(self, contract_address: str) -> dict:
        if contract_address not in self.recent_whale_buys:
            return {"score": 0, "whale_count": 0, "recent": False}
        data = self.recent_whale_buys[contract_address]
        return {
            "score": min(len(data.get("wallets", [])) * 25, 100),
            "whale_count": len(data.get("wallets", [])),
            "recent": True
        }

whale_tracker = WhaleTracker()
