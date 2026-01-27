import asyncio
import aiohttp
from datetime import datetime
from config import settings
from typing import Optional
import re

class SocialScraper:
    """Aggregates crypto mentions from multiple social sources"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def scrape_all_sources(self) -> list[dict]:
        """Scrape all configured sources and return aggregated mentions"""
        all_mentions = []
        
        results = await asyncio.gather(
            self.scrape_coingecko_trending(),
            self.scrape_coingecko_gainers(),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        return all_mentions
    
    async def scrape_coingecko_trending(self) -> list[dict]:
        """Get trending coins from CoinGecko (free, no API key)"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/search/trending",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    print(f"CoinGecko trending returned {resp.status}")
                    return mentions
                
                data = await resp.json()
                trending = data.get("coins", [])
                
                for i, coin in enumerate(trending):
                    item = coin.get("item", {})
                    symbol = item.get("symbol", "").upper()
                    name = item.get("name", "")
                    
                    # Higher rank = more trending = higher score
                    score = (15 - i) * 20  # Top gets 300, decreasing
                    
                    if score > 0:
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_trending",
                            "count": score
                        })
                        print(f"📈 Trending #{i+1}: {symbol} ({name}) - score {score}")
                        
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        
        return mentions
    
    async def scrape_coingecko_gainers(self) -> list[dict]:
        """Get top gainers - coins with big price moves often have buzz"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "percent_change_24h_desc",
                    "per_page": 20,
                    "page": 1,
                    "sparkline": False
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    print(f"CoinGecko gainers returned {resp.status}")
                    return mentions
                
                coins = await resp.json()
                
                for coin in coins:
                    symbol = coin.get("symbol", "").upper()
                    change = coin.get("price_change_percentage_24h", 0) or 0
                    
                    # Only count significant gainers as "buzz"
                    if change > 10:
                        score = int(change * 5)  # 20% gain = 100 score
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_gainers",
                            "count": score
                        })
                        print(f"🚀 Gainer: {symbol} +{change:.1f}% - score {score}")
                        
        except Exception as e:
            print(f"CoinGecko gainers error: {e}")
        
        return mentions
