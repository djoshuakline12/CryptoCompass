import asyncio
import aiohttp
from typing import Optional
from config import settings

class SocialScraper:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def passes_market_cap_filter(self, market_cap: float) -> bool:
        """Check if coin passes user's market cap filter"""
        if market_cap == 0:
            return True  # Unknown market cap, let it through
        return settings.min_market_cap <= market_cap <= settings.max_market_cap
    
    async def scrape_all_sources(self) -> list[dict]:
        all_mentions = []
        results = await asyncio.gather(
            self.scrape_coingecko_trending(),
            self.scrape_coingecko_movers(),
            self.scrape_dexscreener_gainers(),
            self.scrape_dexscreener_boosted(),
            self.scrape_coinmarketcap_trending(),
            return_exceptions=True
        )
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        # Remove duplicates, keeping highest score
        seen = {}
        for m in all_mentions:
            coin = m["coin"]
            if coin not in seen or m["count"] > seen[coin]["count"]:
                seen[coin] = m
        
        final = list(seen.values())
        print(f"📊 Signals after market cap filter (${settings.min_market_cap:,.0f} - ${settings.max_market_cap:,.0f}): {len(final)}")
        return final
    
    async def scrape_coingecko_trending(self) -> list[dict]:
        """Get trending coins, filtered by user's market cap settings"""
        mentions = []
        session = await self.get_session()
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/search/trending",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                data = await resp.json()
                trending = data.get("coins", [])
                
                for i, coin in enumerate(trending):
                    item = coin.get("item", {})
                    symbol = item.get("symbol", "").upper()
                    market_cap = item.get("data", {}).get("market_cap", 0) or 0
                    
                    if not self.passes_market_cap_filter(market_cap):
                        continue
                    
                    score = (15 - i) * 25
                    if score > 0:
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_trending",
                            "count": score,
                            "market_cap": market_cap
                        })
                        print(f"📈 Trending: {symbol} (mcap: ${market_cap:,.0f})")
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        return mentions
    
    async def scrape_coingecko_movers(self) -> list[dict]:
        """Find coins with big price moves within market cap range"""
        mentions = []
        session = await self.get_session()
        try:
            # Determine which page to fetch based on market cap target
            # Page 1 = top 250, Page 2 = 251-500, etc.
            pages = [1, 2, 3] if settings.max_market_cap > 1_000_000_000 else [2, 3, 4]
            
            for page in pages:
                async with session.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": "250",
                        "page": str(page),
                        "price_change_percentage": "24h"
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        continue
                    coins = await resp.json()
                    
                    for coin in coins:
                        symbol = coin.get("symbol", "").upper()
                        change_24h = coin.get("price_change_percentage_24h") or 0
                        market_cap = coin.get("market_cap") or 0
                        volume = coin.get("total_volume") or 0
                        
                        if not self.passes_market_cap_filter(market_cap):
                            continue
                        
                        # Look for movers with decent volume
                        if change_24h > 10 and volume > 500_000:
                            score = int(change_24h * 8)
                            mentions.append({
                                "coin": symbol,
                                "source": "price_mover",
                                "count": min(score, 400),
                                "market_cap": market_cap,
                                "change_24h": round(change_24h, 1)
                            })
                            print(f"🚀 Mover: {symbol} +{change_24h:.1f}% (mcap: ${market_cap:,.0f})")
        except Exception as e:
            print(f"Movers error: {e}")
        return mentions
    
    async def scrape_dexscreener_gainers(self) -> list[dict]:
        """Get DEX gainers filtered by FDV (proxy for market cap)"""
        mentions = []
        session = await self.get_session()
        try:
            chains = ["solana", "base", "ethereum"]
            
            for chain in chains:
                async with session.get(
                    f"https://api.dexscreener.com/latest/dex/pairs/{chain}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    pairs = data.get("pairs", [])[:50]
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        price_change = float(pair.get("priceChange", {}).get("h24") or 0)
                        volume_24h = float(pair.get("volume", {}).get("h24") or 0)
                        liquidity = float(pair.get("liquidity", {}).get("usd") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        
                        # Use FDV as proxy for market cap
                        if not self.passes_market_cap_filter(fdv):
                            continue
                        
                        if volume_24h > 50_000 and liquidity > 30_000 and price_change > 15:
                            score = int((price_change * 3) + (volume_24h / 50_000))
                            mentions.append({
                                "coin": symbol,
                                "source": f"dex_{chain}",
                                "count": min(score, 500),
                                "market_cap": fdv,
                                "change_24h": round(price_change, 1)
                            })
                            print(f"💎 DEX ({chain}): {symbol} +{price_change:.0f}% (fdv: ${fdv:,.0f})")
        except Exception as e:
            print(f"DexScreener gainers error: {e}")
        return mentions
    
    async def scrape_dexscreener_boosted(self) -> list[dict]:
        """Get boosted tokens"""
        mentions = []
        session = await self.get_session()
        try:
            async with session.get(
                "https://api.dexscreener.com/token-boosts/latest/v1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                tokens = await resp.json()
                
                for i, token in enumerate(tokens[:30] if isinstance(tokens, list) else []):
                    symbol = token.get("tokenSymbol", "").upper()
                    if symbol:
                        score = 250 - (i * 8)
                        mentions.append({
                            "coin": symbol,
                            "source": "dex_boosted",
                            "count": max(score, 50),
                            "market_cap": 0  # Unknown
                        })
                        print(f"⚡ Boosted: {symbol}")
        except Exception as e:
            print(f"DexScreener boosted error: {e}")
        return mentions
    
    async def scrape_coinmarketcap_trending(self) -> list[dict]:
        """CMC trending"""
        mentions = []
        session = await self.get_session()
        try:
            async with session.get(
                "https://api.coinmarketcap.com/data-api/v3/topsearch/rank",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                data = await resp.json()
                trending = data.get("data", {}).get("cryptoTopSearchRanks", [])
                
                for i, coin in enumerate(trending[:20]):
                    symbol = coin.get("symbol", "").upper()
                    market_cap = coin.get("marketCap", 0) or 0
                    
                    if market_cap and not self.passes_market_cap_filter(market_cap):
                        continue
                    
                    if symbol:
                        score = (20 - i) * 12
                        mentions.append({
                            "coin": symbol,
                            "source": "cmc_trending",
                            "count": score,
                            "market_cap": market_cap
                        })
                        print(f"🔍 CMC: {symbol}")
        except Exception as e:
            print(f"CMC trending error: {e}")
        return mentions
