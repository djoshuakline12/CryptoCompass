import aiohttp
import asyncio
from datetime import datetime, timezone

class SignalAggregator:
    def __init__(self):
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_all_signals(self) -> list:
        """Aggregate signals from multiple sources"""
        signals = []
        
        # Run all sources concurrently
        results = await asyncio.gather(
            self.get_gecko_trending(),
            self.get_dexscreener_trending(),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                signals.extend(result)
        
        return signals
    
    async def get_gecko_trending(self) -> list:
        """Get trending from CoinGecko"""
        signals = []
        session = await self.get_session()
        
        try:
            # Solana trending
            url = "https://api.coingecko.com/api/v3/search/trending"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for coin in data.get("coins", [])[:10]:
                        item = coin.get("item", {})
                        signals.append({
                            "coin": item.get("symbol", "").upper(),
                            "source": "gecko_trending",
                            "score": item.get("score", 0),
                            "market_cap_rank": item.get("market_cap_rank"),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
        except Exception as e:
            print(f"Gecko trending error: {e}")
        
        return signals
    
    async def get_dexscreener_trending(self) -> list:
        """Get trending from DexScreener"""
        signals = []
        session = await self.get_session()
        
        try:
            # Solana gainers
            url = "https://api.dexscreener.com/token-boosts/top/v1"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for token in data[:20] if isinstance(data, list) else []:
                        if token.get("chainId") == "solana":
                            signals.append({
                                "coin": token.get("tokenAddress", "")[:8],
                                "source": "dex_boosted",
                                "url": token.get("url"),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
            
            # Also check Solana pairs
            url = "https://api.dexscreener.com/latest/dex/tokens/solana"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])[:30]
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "")
                        if symbol:
                            signals.append({
                                "coin": symbol.upper(),
                                "source": "gecko_solana",
                                "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
                                "volume_24h": pair.get("volume", {}).get("h24", 0),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
        except Exception as e:
            print(f"DexScreener error: {e}")
        
        return signals
