from datetime import datetime
from config import settings
from database import Database

class AnomalyDetector:
    def __init__(self, db: Database):
        self.db = db
    
    async def detect_signals(self) -> list[dict]:
        signals = []
        
        # Get all recent mentions and treat high-scoring ones as signals
        all_mentions = await self.db.get_all_recent_mentions()
        
        # Group by coin and sum scores
        coin_scores = {}
        for mention in all_mentions:
            coin = mention.get("coin", "")
            count = mention.get("count", 0)
            if coin:
                coin_scores[coin] = coin_scores.get(coin, 0) + count
        
        # Top scoring coins become signals
        sorted_coins = sorted(coin_scores.items(), key=lambda x: x[1], reverse=True)
        
        for coin, score in sorted_coins[:10]:  # Top 10 coins
            if score >= 50:  # Minimum score threshold
                signal = {
                    "coin": coin,
                    "current_mentions": score,
                    "baseline_mentions": 0,
                    "percent_above_baseline": score,  # Use score as %
                    "threshold": settings.buzz_threshold
                }
                signals.append(signal)
                await self.db.save_signal(signal)
                print(f"🚨 SIGNAL: {coin} (score: {score})")
        
        return signals
