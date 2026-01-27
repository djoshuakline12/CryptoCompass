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
    
    def passes_market_cap_filter(self, market_cap) -> bool:
        try:
            mc = float(market_cap or 0)
            if mc == 0:
                return True
            min_mc = float(settings.min_market_cap)
            max_mc = float(settings.max_market_cap)
            return min_mc <= mc <= max_mc
        except:
            return True
    
    async def scrape_all_sources(self) -> list[dict]:
        all_mentions = []
        results = await asyncio.gather(
            self.scrape_coingecko_trending(),
            self.scrape_coingecko_movers(),
            self.scrape_coinmarketcap_trending(),
            return_exceptions=True
        )
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        seen = {}
        for m in all_mentions:
            coin = m["coin"]
            if coin not in seen or m["count"] > seen[coin]["count"]:
                seen[coin] = m
        
        final = list(seen.values())
        print(f"📊 Signals after filter: {len(final)}")
        return final
    
    async def scrape_coingecko_trending(self) -> list[dict]:
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
                    market_cap_str = item.get("data", {}).get("market_cap", "0")
                    try:
                        market_cap = float(str(market_cap_str).replace(",", "").replace("$", "")) if market_cap_str else 0
                    except:
                        market_cap = 0
                    
                    if not self.passes_market_cap_filter(market_cap):
                        continue
                    
                    score = (15 - i) * 25
                    if score > 0:
                        mentions.append({
                            "coin": symbol,
                            "source": "cg_trending",
                            "count": score,
                            "market_cap": market_cap
                        })
                        print(f"📈 Trending: {symbol}")
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        return mentions
    
    async def scrape_coingecko_movers(self) -> list[dict]:
        mentions = []
        session = await self.get_session()
        try:
            for page in [2, 3, 4]:
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
                        change_24h = float(coin.get("price_change_percentage_24h") or 0)
                        market_cap = float(coin.get("market_cap") or 0)
                        volume = float(coin.get("total_volume") or 0)
                        
                        if not self.passes_market_cap_filter(market_cap):
                            continue
                        
                        if change_24h > 10 and volume > 500_000:
                            score = int(change_24h * 8)
                            mentions.append({
                                "coin": symbol,
                                "source": "price_mover",
                                "count": min(score, 400),
                                "market_cap": market_cap,
                                "change_24h": round(change_24h, 1)
                            })
                            print(f"🚀 Mover: {symbol} +{change_24h:.1f}%")
        except Exception as e:
            print(f"Movers error: {e}")
        return mentions
    
    async def scrape_coinmarketcap_trending(self) -> list[dict]:
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
                    if symbol:
                        score = (20 - i) * 12
                        mentions.append({"coin": symbol, "source": "cmc_trending", "count": score, "market_cap": 0})
                        print(f"🔍 CMC: {symbol}")
        except Exception as e:
            print(f"CMC trending error: {e}")
        return mentions
