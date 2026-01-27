from datetime import datetime
from config import settings
from database import Database

class AnomalyDetector:
    def __init__(self, db: Database):
        self.db = db
    
    async def detect_signals(self) -> list[dict]:
        signals = []
        
        all_mentions = await self.db.get_all_recent_mentions()
        
        # Group by coin, sum scores, keep market cap
        coin_data = {}
        for mention in all_mentions:
            coin = mention.get("coin", "")
            count = mention.get("count", 0)
            market_cap = mention.get("market_cap", 0)
            change_24h = mention.get("change_24h", 0)
            
            if coin:
                if coin not in coin_data:
                    coin_data[coin] = {"score": 0, "market_cap": market_cap, "change_24h": change_24h}
                coin_data[coin]["score"] += count
                # Keep the non-zero market cap if we find one
                if market_cap and market_cap > 0:
                    coin_data[coin]["market_cap"] = market_cap
                if change_24h and change_24h > 0:
                    coin_data[coin]["change_24h"] = change_24h
        
        # Top scoring coins become signals
        sorted_coins = sorted(coin_data.items(), key=lambda x: x[1]["score"], reverse=True)
        
        for coin, data in sorted_coins[:10]:
            if data["score"] >= 50:
                signal = {
                    "coin": coin,
                    "current_mentions": data["score"],
                    "baseline_mentions": 0,
                    "percent_above_baseline": data["score"],
                    "threshold": settings.buzz_threshold,
                    "market_cap": data["market_cap"],
                    "change_24h": data.get("change_24h", 0)
                }
                signals.append(signal)
                await self.db.save_signal(signal)
                print(f"🚨 SIGNAL: {coin} (score: {data['score']}, mcap: ${data['market_cap']:,.0f})")
        
        return signals
