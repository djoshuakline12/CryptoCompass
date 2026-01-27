import aiohttp
import asyncio
from datetime import datetime, timezone

class SignalAggregator:
    def __init__(self):
        self.session = None
        self.token_cache = {}
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_token_details(self, symbol: str) -> dict:
        """Get market cap and other details from DexScreener"""
        if symbol in self.token_cache:
            cached = self.token_cache[symbol]
            if (datetime.now(timezone.utc) - cached["time"]).seconds < 300:
                return cached["data"]
        
        session = await self.get_session()
        data = {"market_cap": 0, "liquidity": 0, "volume_24h": 0, "price": 0}
        
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    pairs = result.get("pairs") or []
                    
                    for pair in pairs:
                        if pair.get("chainId") == "solana":
                            pair_symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                            if pair_symbol == symbol.upper():
                                data["market_cap"] = float(pair.get("fdv") or 0)
                                data["liquidity"] = float(pair.get("liquidity", {}).get("usd") or 0)
                                data["volume_24h"] = float(pair.get("volume", {}).get("h24") or 0)
                                data["price"] = float(pair.get("priceUsd") or 0)
                                data["price_change_24h"] = float(pair.get("priceChange", {}).get("h24") or 0)
                                break
        except Exception as e:
            pass
        
        self.token_cache[symbol] = {"data": data, "time": datetime.now(timezone.utc)}
        return data
    
    async def get_all_signals(self) -> list:
        signals = []
        
        results = await asyncio.gather(
            self.get_gecko_trending(),
            self.get_dexscreener_gainers(),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                signals.extend(result)
        
        # Enrich signals with market data
        enriched = []
        for signal in signals:
            details = await self.get_token_details(signal["coin"])
            signal.update({
                "market_cap": details.get("market_cap", 0),
                "liquidity": details.get("liquidity", 0),
                "volume_24h": details.get("volume_24h", 0),
                "price": details.get("price", 0),
                "price_change_24h": details.get("price_change_24h", 0),
                # Placeholder buzz metrics
                "current_mentions": signal.get("score", 1) * 10,
                "baseline_mentions": 5,
                "percent_above_baseline": max(0, (signal.get("score", 1) * 10 - 5) / 5 * 100)
            })
            enriched.append(signal)
        
        return enriched
    
    async def get_gecko_trending(self) -> list:
        signals = []
        session = await self.get_session()
        
        try:
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
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
        except Exception as e:
            print(f"Gecko error: {e}")
        
        return signals
    
    async def get_dexscreener_gainers(self) -> list:
        signals = []
        session = await self.get_session()
        
        try:
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    
                    for pair in pairs[:30]:
                        if pair and pair.get("chainId") == "solana":
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            if symbol:
                                signals.append({
                                    "coin": symbol.upper(),
                                    "source": "dex_solana",
                                    "score": 5,
                                    "price_change_24h": float(pair.get("priceChange", {}).get("h24") or 0),
                                    "volume_24h": float(pair.get("volume", {}).get("h24") or 0),
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except Exception as e:
            print(f"DexScreener error: {e}")
        
        return signals
