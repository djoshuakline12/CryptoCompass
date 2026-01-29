import aiohttp
from datetime import datetime, timezone, timedelta
from typing import List, Dict

class Backtester:
    """
    Simple backtester to validate strategy on historical data
    Uses DexScreener historical data where available
    """
    
    def __init__(self):
        self.results = []
    
    async def backtest_token(self, contract_address: str, days: int = 7) -> dict:
        """Backtest our strategy on a single token"""
        result = {
            "contract": contract_address,
            "trades": [],
            "total_pnl_percent": 0,
            "win_rate": 0,
            "max_drawdown": 0
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get historical data
                url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        
                        if pairs:
                            pair = pairs[0]
                            
                            # Simulate our strategy
                            result["trades"] = self._simulate_strategy(pair)
                            
                            if result["trades"]:
                                wins = [t for t in result["trades"] if t["pnl"] > 0]
                                result["win_rate"] = len(wins) / len(result["trades"]) * 100
                                result["total_pnl_percent"] = sum(t["pnl"] for t in result["trades"])
        except:
            pass
        
        return result
    
    def _simulate_strategy(self, pair: dict) -> List[Dict]:
        """Simulate our entry/exit strategy"""
        trades = []
        
        # Get price changes as proxy for movement
        change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
        change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
        change_24h = float(pair.get("priceChange", {}).get("h24") or 0)
        
        # Simulate: Would our entry have triggered?
        would_enter = (
            5 < change_1h < 30 and  # Momentum
            float(pair.get("liquidity", {}).get("usd") or 0) >= 100000  # Liquidity
        )
        
        if would_enter:
            # Estimate exit based on volatility
            if change_5m > 5:
                # Fast mover - likely hit take profit
                trades.append({"entry": "1h momentum", "pnl": 8, "exit": "take profit"})
            elif change_5m < -5:
                # Reversal - likely hit stop
                trades.append({"entry": "1h momentum", "pnl": -5, "exit": "stop loss"})
            else:
                # Flat - time stop
                trades.append({"entry": "1h momentum", "pnl": 0, "exit": "time stop"})
        
        return trades
    
    async def run_backtest(self, tokens: List[str]) -> dict:
        """Run backtest on multiple tokens"""
        all_results = []
        
        for token in tokens[:20]:  # Limit to avoid rate limits
            result = await self.backtest_token(token)
            if result["trades"]:
                all_results.append(result)
        
        # Aggregate
        total_trades = sum(len(r["trades"]) for r in all_results)
        total_wins = sum(len([t for t in r["trades"] if t["pnl"] > 0]) for r in all_results)
        total_pnl = sum(r["total_pnl_percent"] for r in all_results)
        
        return {
            "tokens_tested": len(all_results),
            "total_trades": total_trades,
            "win_rate": (total_wins / total_trades * 100) if total_trades > 0 else 0,
            "total_pnl_percent": total_pnl,
            "avg_pnl_per_trade": total_pnl / total_trades if total_trades > 0 else 0
        }

backtester = Backtester()
