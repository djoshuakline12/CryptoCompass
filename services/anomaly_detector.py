from database import Database

class AnomalyDetector:
    def __init__(self, db: Database):
        self.db = db
    
    async def detect_signals(self) -> list:
        mentions = await self.db.get_all_recent_mentions()
        
        if not mentions:
            return []
        
        coin_data = {}
        for m in mentions:
            coin = m.get("coin", "").upper()
            if not coin:
                continue
            
            count = m.get("count", 0)
            source = m.get("source", "unknown")
            market_cap = m.get("market_cap", 0)
            age_hours = m.get("age_hours", 999)
            
            if coin not in coin_data:
                coin_data[coin] = {
                    "total_count": 0,
                    "best_source": source,
                    "best_count": count,
                    "market_cap": market_cap,
                    "age_hours": age_hours
                }
            
            coin_data[coin]["total_count"] += count
            
            if count > coin_data[coin]["best_count"]:
                coin_data[coin]["best_source"] = source
                coin_data[coin]["best_count"] = count
            
            if market_cap > coin_data[coin]["market_cap"]:
                coin_data[coin]["market_cap"] = market_cap
            
            if age_hours < coin_data[coin]["age_hours"]:
                coin_data[coin]["age_hours"] = age_hours
        
        signals = []
        for coin, data in coin_data.items():
            signal = {
                "coin": coin,
                "current_mentions": data["total_count"],
                "baseline_mentions": 0,
                "percent_above_baseline": data["total_count"],
                "source": data["best_source"],
                "market_cap": data["market_cap"],
                "age_hours": data["age_hours"]
            }
            signals.append(signal)
            await self.db.save_signal(signal)
        
        signals.sort(key=lambda x: x["current_mentions"], reverse=True)
        print(f"🎯 {len(signals)} signals")
        
        return signals[:20]
