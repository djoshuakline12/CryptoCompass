from datetime import datetime
from config import settings
from database import Database

class AnomalyDetector:
    """Detects early buzz by finding coins with mention spikes above baseline"""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def detect_signals(self) -> list[dict]:
        """
        Find coins where recent mentions significantly exceed baseline.
        This is where we catch "early buzz" before price moves.
        """
        signals = []
        
        for coin in settings.tracked_coins:
            try:
                signal = await self.analyze_coin(coin)
                if signal:
                    signals.append(signal)
                    await self.db.save_signal(signal)
                    print(f"🚨 SIGNAL: {coin} is {signal['percent_above_baseline']:.0f}% above baseline!")
                    
            except Exception as e:
                print(f"Error analyzing {coin}: {e}")
        
        return signals
    
    async def analyze_coin(self, coin: str) -> dict | None:
        """
        Analyze a single coin for buzz anomaly.
        Returns signal dict if anomaly detected, None otherwise.
        """
        # Get baseline (average hourly mentions over past week)
        baseline = await self.db.get_baseline(coin)
        
        # Skip coins with very low baseline (not enough data)
        if baseline < settings.min_baseline_mentions:
            return None
        
        # Get recent mentions (last hour)
        recent = await self.db.get_recent_mentions(coin, hours=1)
        
        # Calculate percent above baseline
        if baseline == 0:
            return None
            
        percent_above = ((recent - baseline) / baseline) * 100
        
        # Check if this exceeds our threshold
        if percent_above >= settings.buzz_threshold:
            return {
                "coin": coin,
                "current_mentions": recent,
                "baseline_mentions": round(baseline, 1),
                "percent_above_baseline": round(percent_above, 1),
                "threshold": settings.buzz_threshold
            }
        
        return None
    
    async def get_buzz_scores(self) -> list[dict]:
        """
        Get buzz scores for all tracked coins (for dashboard display).
        Returns sorted list with highest buzz first.
        """
        scores = []
        
        for coin in settings.tracked_coins:
            baseline = await self.db.get_baseline(coin)
            recent = await self.db.get_recent_mentions(coin, hours=1)
            
            if baseline > 0:
                percent_above = ((recent - baseline) / baseline) * 100
            else:
                percent_above = 0
            
            scores.append({
                "coin": coin,
                "recent_mentions": recent,
                "baseline": round(baseline, 1),
                "buzz_score": round(percent_above, 1)
            })
        
        # Sort by buzz score descending
        scores.sort(key=lambda x: x["buzz_score"], reverse=True)
        return scores
