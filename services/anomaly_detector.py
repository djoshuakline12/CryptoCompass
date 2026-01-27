from datetime import datetime
from config import settings
from database import Database

class AnomalyDetector:
    def __init__(self, db: Database):
        self.db = db
    
    async def detect_signals(self) -> list[dict]:
        signals = []
        
        for coin in settings.tracked_coins:
            try:
                signal = await self.analyze_coin(coin)
                if signal:
                    signals.append(signal)
                    await self.db.save_signal(signal)
                    print(f"SIGNAL: {coin} is {signal['percent_above_baseline']:.0f}% above baseline!")
            except Exception as e:
                print(f"Error analyzing {coin}: {e}")
        
        # Also check for any coin with high recent mentions (for early detection)
        hot_coins = await self.detect_hot_coins()
        for signal in hot_coins:
            if signal["coin"] not in [s["coin"] for s in signals]:
                signals.append(signal)
                await self.db.save_signal(signal)
        
        return signals
    
    async def analyze_coin(self, coin: str) -> dict | None:
        baseline = await self.db.get_baseline(coin)
        
        if baseline < settings.min_baseline_mentions:
            return None
        
        recent = await self.db.get_recent_mentions(coin, hours=1)
        
        if baseline == 0:
            return None
            
        percent_above = ((recent - baseline) / baseline) * 100
        
        if percent_above >= settings.buzz_threshold:
            return {
                "coin": coin,
                "current_mentions": recent,
                "baseline_mentions": round(baseline, 1),
                "percent_above_baseline": round(percent_above, 1),
                "threshold": settings.buzz_threshold
            }
        
        return None
    
    async def detect_hot_coins(self) -> list[dict]:
        """Detect coins with high activity even without baseline comparison"""
        signals = []
        
        # Get all recent mentions
        for coin in settings.tracked_coins:
            recent = await self.db.get_recent_mentions(coin, hours=1)
            
            # If a coin has significant mentions, flag it
            if recent >= 100:  # High absolute activity
                signals.append({
                    "coin": coin,
                    "current_mentions": recent,
                    "baseline_mentions": 0,
                    "percent_above_baseline": 999,  # Mark as hot
                    "threshold": settings.buzz_threshold
                })
                print(f"HOT COIN: {coin} with {recent} mentions")
        
        return signals
