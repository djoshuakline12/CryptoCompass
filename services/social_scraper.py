import asyncio
import aiohttp
from datetime import datetime, timedelta
from config import settings
from typing import Optional
import re

class SocialScraper:
    """Aggregates crypto mentions from multiple social sources"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Regex patterns to find coin mentions
        self.coin_patterns = {
            coin: re.compile(rf'\$?{coin}\b', re.IGNORECASE) 
            for coin in settings.tracked_coins
        }
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def scrape_all_sources(self) -> list[dict]:
        """Scrape all configured sources and return aggregated mentions"""
        all_mentions = []
        
        # Run all scrapers concurrently
        results = await asyncio.gather(
            self.scrape_reddit(),
            self.scrape_lunarcrush(),
            # Add more sources here
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        return all_mentions
    
    async def scrape_reddit(self) -> list[dict]:
        """Scrape crypto subreddits for coin mentions"""
        mentions = []
        
        if not settings.reddit_client_id:
            print("⚠️  Reddit not configured")
            return mentions
        
        session = await self.get_session()
        
        subreddits = [
            "cryptocurrency", 
            "CryptoMoonShots",
            "SatoshiStreetBets",
            "altcoin",
            "defi"
        ]
        
        try:
            # Get Reddit access token
            auth = aiohttp.BasicAuth(settings.reddit_client_id, settings.reddit_client_secret)
            async with session.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=auth,
                headers={"User-Agent": "CryptoBuzzBot/1.0"}
            ) as resp:
                token_data = await resp.json()
                token = token_data.get("access_token")
            
            if not token:
                return mentions
            
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "CryptoBuzzBot/1.0"
            }
            
            # Count mentions per coin across subreddits
            coin_counts = {coin: 0 for coin in settings.tracked_coins}
            
            for subreddit in subreddits:
                async with session.get(
                    f"https://oauth.reddit.com/r/{subreddit}/new",
                    headers=headers,
                    params={"limit": 100}
                ) as resp:
                    if resp.status != 200:
                        continue
                    
                    data = await resp.json()
                    posts = data.get("data", {}).get("children", [])
                    
                    for post in posts:
                        post_data = post.get("data", {})
                        text = f"{post_data.get('title', '')} {post_data.get('selftext', '')}"
                        
                        # Count mentions of each coin
                        for coin, pattern in self.coin_patterns.items():
                            if pattern.search(text):
                                coin_counts[coin] += 1
            
            # Convert to mention records
            for coin, count in coin_counts.items():
                if count > 0:
                    mentions.append({
                        "coin": coin,
                        "source": "reddit",
                        "count": count
                    })
                    
        except Exception as e:
            print(f"Reddit scrape error: {e}")
        
        return mentions
    
    async def scrape_lunarcrush(self) -> list[dict]:
        """Get social metrics from LunarCrush API (built for this exact use case)"""
        mentions = []
        
        if not settings.lunarcrush_api_key:
            print("⚠️  LunarCrush not configured")
            return mentions
        
        session = await self.get_session()
        
        try:
            # LunarCrush provides pre-aggregated social metrics
            headers = {"Authorization": f"Bearer {settings.lunarcrush_api_key}"}
            
            async with session.get(
                "https://lunarcrush.com/api4/public/coins/list/v2",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return mentions
                
                data = await resp.json()
                coins_data = data.get("data", [])
                
                for coin_data in coins_data:
                    symbol = coin_data.get("symbol", "").upper()
                    
                    if symbol in settings.tracked_coins:
                        # LunarCrush provides social_volume (mentions across platforms)
                        social_volume = coin_data.get("social_volume", 0)
                        
                        if social_volume > 0:
                            mentions.append({
                                "coin": symbol,
                                "source": "lunarcrush",
                                "count": social_volume
                            })
                            
        except Exception as e:
            print(f"LunarCrush scrape error: {e}")
        
        return mentions
    
    async def scrape_coingecko_trending(self) -> list[dict]:
        """Get trending coins from CoinGecko (free, no API key)"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/search/trending"
            ) as resp:
                if resp.status != 200:
                    return mentions
                
                data = await resp.json()
                trending = data.get("coins", [])
                
                for i, coin in enumerate(trending):
                    item = coin.get("item", {})
                    symbol = item.get("symbol", "").upper()
                    
                    if symbol in settings.tracked_coins:
                        # Higher rank = more trending = higher "mention" equivalent
                        score = (10 - i) * 10  # Top trending gets 100, second gets 90, etc.
                        mentions.append({
                            "coin": symbol,
                            "source": "coingecko_trending",
                            "count": score
                        })
                        
        except Exception as e:
            print(f"CoinGecko scrape error: {e}")
        
        return mentions
