from datetime import datetime, timezone, timedelta
from typing import Optional
import json

class AIScorer:
    """Multi-factor scoring with continuous learning"""
    
    def __init__(self, db):
        self.db = db
        self.weights = {
            # Social signals
            "buzz_score": 0.20,
            "multi_source": 0.10,
            "social_velocity": 0.10,
            
            # Technical signals
            "price_momentum": 0.15,
            "volume_surge": 0.15,
            "liquidity_health": 0.10,
            
            # On-chain signals
            "buy_pressure": 0.10,
            "freshness": 0.10
        }
        
        # Learning data
        self.source_performance = {}
        self.mcap_performance = {}
        self.hour_performance = {}
        self.factor_performance = {}
        
    async def learn_from_history(self):
        """Analyze past trades to adjust weights"""
        trades = await self.db.get_trade_history(500)
        
        if len(trades) < 10:
            print("📚 Not enough trades to learn from yet")
            return
        
        # Analyze by source
        self.source_performance = {}
        for t in trades:
            source = t.get("signal_source", "unknown")
            if source not in self.source_performance:
                self.source_performance[source] = {"wins": 0, "losses": 0, "total_pnl": 0}
            
            if t.get("pnl_percent", 0) > 0:
                self.source_performance[source]["wins"] += 1
            else:
                self.source_performance[source]["losses"] += 1
            self.source_performance[source]["total_pnl"] += t.get("pnl_percent", 0)
        
        # Analyze by market cap range
        self.mcap_performance = {"micro": {"wins": 0, "losses": 0}, "small": {"wins": 0, "losses": 0}, "mid": {"wins": 0, "losses": 0}}
        for t in trades:
            mcap = t.get("market_cap", 0)
            if mcap < 10_000_000:
                bucket = "micro"
            elif mcap < 100_000_000:
                bucket = "small"
            else:
                bucket = "mid"
            
            if t.get("pnl_percent", 0) > 0:
                self.mcap_performance[bucket]["wins"] += 1
            else:
                self.mcap_performance[bucket]["losses"] += 1
        
        # Analyze by hour of day
        self.hour_performance = {}
        for t in trades:
            try:
                buy_time = datetime.fromisoformat(t.get("buy_time", "").replace('Z', '+00:00'))
                hour = buy_time.hour
                if hour not in self.hour_performance:
                    self.hour_performance[hour] = {"wins": 0, "losses": 0}
                if t.get("pnl_percent", 0) > 0:
                    self.hour_performance[hour]["wins"] += 1
                else:
                    self.hour_performance[hour]["losses"] += 1
            except:
                pass
        
        # Calculate win rates
        print("📊 Learning from history:")
        for source, data in self.source_performance.items():
            total = data["wins"] + data["losses"]
            if total > 0:
                wr = data["wins"] / total * 100
                print(f"   {source}: {wr:.0f}% win rate ({total} trades)")
    
    def get_source_multiplier(self, source: str) -> float:
        """Get performance multiplier for a source"""
        if source not in self.source_performance:
            return 1.0
        
        data = self.source_performance[source]
        total = data["wins"] + data["losses"]
        
        if total < 3:
            return 1.0
        
        win_rate = data["wins"] / total
        
        # Scale: 0% WR = 0.5x, 50% WR = 1.0x, 100% WR = 1.5x
        return 0.5 + win_rate
    
    def get_hour_multiplier(self) -> float:
        """Get multiplier based on current hour performance"""
        hour = datetime.now(timezone.utc).hour
        
        if hour not in self.hour_performance:
            return 1.0
        
        data = self.hour_performance[hour]
        total = data["wins"] + data["losses"]
        
        if total < 3:
            return 1.0
        
        win_rate = data["wins"] / total
        return 0.7 + (win_rate * 0.6)  # Range: 0.7 to 1.3
    
    async def score_opportunity(self, coin: str, signal: dict, token_data: dict) -> dict:
        """Score a trading opportunity with multiple factors"""
        
        scores = {}
        reasons = []
        
        # 1. BUZZ SCORE (social mentions)
        mentions = signal.get("current_mentions", 0)
        if mentions >= 500:
            scores["buzz_score"] = 100
            reasons.append(f"🔥 Very high buzz ({mentions} mentions)")
        elif mentions >= 300:
            scores["buzz_score"] = 80
            reasons.append(f"📈 High buzz ({mentions} mentions)")
        elif mentions >= 200:
            scores["buzz_score"] = 60
            reasons.append(f"📊 Moderate buzz ({mentions} mentions)")
        else:
            scores["buzz_score"] = max(20, mentions / 5)
        
        # 2. MULTI-SOURCE (appearing on multiple platforms)
        num_sources = signal.get("num_sources", 1)
        if num_sources >= 4:
            scores["multi_source"] = 100
            reasons.append(f"🌐 Trending on {num_sources} platforms")
        elif num_sources >= 2:
            scores["multi_source"] = 60
            reasons.append(f"📡 Found on {num_sources} sources")
        else:
            scores["multi_source"] = 30
        
        # 3. SOCIAL VELOCITY (how fast mentions are growing)
        # Approximated by age - newer signals = higher velocity
        age_hours = signal.get("age_hours", 24)
        if age_hours < 2:
            scores["social_velocity"] = 100
            reasons.append("⚡ Breaking now (< 2 hours old)")
        elif age_hours < 6:
            scores["social_velocity"] = 80
            reasons.append("🆕 Fresh signal (< 6 hours)")
        elif age_hours < 12:
            scores["social_velocity"] = 50
        else:
            scores["social_velocity"] = 20
        
        # 4. PRICE MOMENTUM
        change_5m = token_data.get("change_5m", 0)
        change_1h = token_data.get("change_1h", 0)
        change_24h = token_data.get("change_24h", 0)
        
        momentum_score = 0
        if 5 <= change_5m <= 30:  # Good short-term momentum, not too crazy
            momentum_score += 40
            reasons.append(f"📈 +{change_5m:.1f}% in 5m")
        if 10 <= change_1h <= 50:
            momentum_score += 35
        if 20 <= change_24h <= 100:
            momentum_score += 25
        elif change_24h > 100:  # Already pumped too much
            momentum_score -= 20
            reasons.append(f"⚠️ Already +{change_24h:.0f}% today")
        
        scores["price_momentum"] = max(0, min(100, momentum_score))
        
        # 5. VOLUME SURGE
        volume_24h = token_data.get("volume_24h", 0)
        volume_1h = token_data.get("volume_1h", 0)
        
        if volume_1h > 0 and volume_24h > 0:
            hourly_avg = volume_24h / 24
            if volume_1h > hourly_avg * 3:
                scores["volume_surge"] = 100
                reasons.append(f"🚀 Volume surge ({volume_1h/hourly_avg:.1f}x normal)")
            elif volume_1h > hourly_avg * 1.5:
                scores["volume_surge"] = 70
            else:
                scores["volume_surge"] = 40
        else:
            scores["volume_surge"] = 30
        
        # 6. LIQUIDITY HEALTH
        liquidity = token_data.get("liquidity", 0)
        if liquidity >= 500_000:
            scores["liquidity_health"] = 100
            reasons.append(f"💧 Strong liquidity (${liquidity/1000:.0f}K)")
        elif liquidity >= 200_000:
            scores["liquidity_health"] = 80
        elif liquidity >= 100_000:
            scores["liquidity_health"] = 60
        elif liquidity >= 50_000:
            scores["liquidity_health"] = 40
        else:
            scores["liquidity_health"] = 20
        
        # 7. BUY PRESSURE
        buys = token_data.get("buys_1h", 0)
        sells = token_data.get("sells_1h", 0)
        
        if buys + sells > 0:
            buy_ratio = buys / (buys + sells)
            if buy_ratio > 0.65:
                scores["buy_pressure"] = 100
                reasons.append(f"🟢 Strong buying ({buy_ratio*100:.0f}% buys)")
            elif buy_ratio > 0.55:
                scores["buy_pressure"] = 70
            elif buy_ratio > 0.45:
                scores["buy_pressure"] = 50
            else:
                scores["buy_pressure"] = 20
                reasons.append(f"🔴 Sell pressure ({(1-buy_ratio)*100:.0f}% sells)")
        else:
            scores["buy_pressure"] = 40
        
        # 8. FRESHNESS (new tokens)
        age_hours = signal.get("age_hours", 999)
        if age_hours < 6:
            scores["freshness"] = 100
            reasons.append("✨ Newly launched")
        elif age_hours < 24:
            scores["freshness"] = 70
        elif age_hours < 72:
            scores["freshness"] = 40
        else:
            scores["freshness"] = 20
        
        # Calculate weighted total
        total_score = sum(scores[k] * self.weights[k] for k in scores)
        
        # Apply learned multipliers
        source = signal.get("source", "unknown")
        source_mult = self.get_source_multiplier(source)
        hour_mult = self.get_hour_multiplier()
        
        adjusted_score = total_score * source_mult * hour_mult
        
        if source_mult > 1.1:
            reasons.append(f"📚 {source} historically profitable")
        elif source_mult < 0.8:
            reasons.append(f"⚠️ {source} historically weak")
        
        # Determine confidence
        if adjusted_score >= 70:
            confidence = "HIGH"
        elif adjusted_score >= 50:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        # Build buy reason summary
        top_reasons = reasons[:4]  # Keep top 4 reasons
        buy_reason = " | ".join(top_reasons) if top_reasons else "General opportunity"
        
        return {
            "coin": coin,
            "total_score": round(adjusted_score, 1),
            "confidence": confidence,
            "factor_scores": scores,
            "source_multiplier": round(source_mult, 2),
            "hour_multiplier": round(hour_mult, 2),
            "buy_reason": buy_reason,
            "reasons": reasons,
            "recommendation": "BUY" if adjusted_score >= 50 else "SKIP"
        }
    
    def get_insights(self) -> dict:
        """Return learning insights for the UI"""
        
        source_stats = {}
        for source, data in self.source_performance.items():
            total = data["wins"] + data["losses"]
            if total > 0:
                source_stats[source] = {
                    "win_rate": round(data["wins"] / total * 100, 1),
                    "total_trades": total,
                    "avg_pnl": round(data["total_pnl"] / total, 2)
                }
        
        best_source = max(source_stats.items(), key=lambda x: x[1]["win_rate"])[0] if source_stats else None
        worst_source = min(source_stats.items(), key=lambda x: x[1]["win_rate"])[0] if source_stats else None
        
        best_hours = []
        for hour, data in self.hour_performance.items():
            total = data["wins"] + data["losses"]
            if total >= 3:
                wr = data["wins"] / total
                if wr > 0.6:
                    best_hours.append(hour)
        
        return {
            "source_stats": source_stats,
            "best_source": best_source,
            "worst_source": worst_source,
            "best_hours_utc": sorted(best_hours),
            "mcap_performance": self.mcap_performance,
            "total_factors": len(self.weights),
            "weights": self.weights
        }
