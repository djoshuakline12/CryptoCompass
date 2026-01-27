import asyncio
import aiohttp
from datetime import datetime
from config import settings
from typing import Optional

class SocialScraper:
    """Aggregates crypto data from multiple free sources"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def scrape_all_sources(self) -> list[dict]:
        """Scrape all sources and return aggregated data"""
        all_mentions = []
        
        results = await asyncio.gather(
            self.scrape_coingecko_trending(),
            self.scrape_coingecko_gainers(),
            self.scrape_dexscreener_boosted(),
            self.scrape_dexscreener_new_pairs(),
            self.scrape_coinmarketcap_trending(),
            self.scrape_coingecko_volume_spike(),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        print(f"📊 Total signals collected: {len(all_mentions)}")
        return all_mentions
    
    async def scrape_coingecko_trending(self) -> list[dict]:
        """Get trending coins from CoinGecko"""
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
                    score = (15 - i) * 20
                    
                    if score > 0:
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_trending",
                            "count": score
                        })
                        print(f"📈 CG Trending #{i+1}: {symbol} (score {score})")
                        
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        
        return mentions
    
    async def scrape_coingecko_gainers(self) -> list[dict]:
        """Get top gainers - big price moves often signal buzz"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "percent_change_24h_desc",
                    "per_page": "50",
                    "page": "1",
                    "sparkline": "false"
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                
                coins = await resp.json()
                
                for coin in coins:
                    symbol = coin.get("symbol", "").upper()
                    change = coin.get("price_change_percentage_24h", 0) or 0
                    
                    if change > 10:
                        score = int(change * 5)
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_gainers",
                            "count": score
                        })
                        print(f"🚀 CG Gainer: {symbol} +{change:.1f}%")
                        
        except Exception as e:
            print(f"CoinGecko gainers error: {e}")
        
        return mentions
    
    async def scrape_coingecko_volume_spike(self) -> list[dict]:
        """Detect unusual volume - often precedes price moves"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "volume_desc",
                    "per_page": "100",
                    "page": "1",
                    "sparkline": "false"
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                
                coins = await resp.json()
                
                for coin in coins:
                    symbol = coin.get("symbol", "").upper()
                    volume = coin.get("total_volume", 0) or 0
                    market_cap = coin.get("market_cap", 0) or 1
                    
                    if market_cap > 0:
                        ratio = volume / market_cap
                        if ratio > 0.3:
                            score = int(ratio * 100)
                            mentions.append({
                                "coin": symbol,
                                "source": "volume_spike",
                                "count": min(score, 500)
                            })
                            print(f"📊 Volume spike: {symbol} (ratio {ratio:.2f})")
                        
        except Exception as e:
            print(f"Volume spike error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_boosted(self) -> list[dict]:
        """Get boosted tokens on DexScreener"""
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
                
                for i, token in enumerate(tokens[:20] if isinstance(tokens, list) else []):
                    symbol = token.get("tokenSymbol", "").upper()
                    if symbol:
                        score = 200 - (i * 10)
                        mentions.append({
                            "coin": symbol,
                            "source": "dexscreener_boosted",
                            "count": max(score, 50)
                        })
                        print(f"💎 DEX Boosted: {symbol}")
                        
        except Exception as e:
            print(f"DexScreener boosted error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_new_pairs(self) -> list[dict]:
        """Get hot trading pairs from DexScreener"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.dexscreener.com/latest/dex/pairs/solana",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                
                data = await resp.json()
                pairs = data.get("pairs", [])[:30]
                
                for pair in pairs:
                    symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                    volume_24h = float(pair.get("volume", {}).get("h24", 0) or 0)
                    liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                    price_change = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                    
                    if volume_24h > 50000 and liquidity > 30000 and price_change > 5:
                        score = int((volume_24h / 10000) + (price_change * 2))
                        mentions.append({
                            "coin": symbol,
                            "source": "dexscreener_hot",
                            "count": min(score, 400)
                        })
                        print(f"🔥 DEX Hot: {symbol} vol=${volume_24h:,.0f} +{price_change:.1f}%")
                        
        except Exception as e:
            print(f"DexScreener pairs error: {e}")
        
        return mentions

    async def scrape_coinmarketcap_trending(self) -> list[dict]:
        """Get CMC trending"""
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
                
                for i, coin in enumerate(trending[:15]):
                    symbol = coin.get("symbol", "").upper()
                    if symbol:
                        score = (15 - i) * 15
                        mentions.append({
                            "coin": symbol,
                            "source": "cmc_trending",
                            "count": score
                        })
                        print(f"🔍 CMC Trending #{i+1}: {symbol}")
                        
        except Exception as e:
            print(f"CMC trending error: {e}")
        
        return mentions
