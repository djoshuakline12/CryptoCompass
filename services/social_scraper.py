import asyncio
import aiohttp
from typing import Optional

class SocialScraper:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def scrape_all_sources(self) -> list[dict]:
        all_mentions = []
        results = await asyncio.gather(
            self.scrape_coingecko_trending(),
            self.scrape_dexscreener_boosted(),
            self.scrape_coinmarketcap_trending(),
            return_exceptions=True
        )
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        print(f"Total signals collected: {len(all_mentions)}")
        return all_mentions
    
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
                    score = (15 - i) * 20
                    if score > 0:
                        mentions.append({"coin": symbol, "source": "coingecko_trending", "count": score})
                        print(f"CG Trending #{i+1}: {symbol} (score {score})")
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        return mentions
    
    async def scrape_dexscreener_boosted(self) -> list[dict]:
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
                        mentions.append({"coin": symbol, "source": "dexscreener_boosted", "count": max(score, 50)})
                        print(f"DEX Boosted: {symbol}")
        except Exception as e:
            print(f"DexScreener boosted error: {e}")
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
                for i, coin in enumerate(trending[:15]):
                    symbol = coin.get("symbol", "").upper()
                    if symbol:
                        score = (15 - i) * 15
                        mentions.append({"coin": symbol, "source": "cmc_trending", "count": score})
                        print(f"CMC Trending #{i+1}: {symbol}")
        except Exception as e:
            print(f"CMC trending error: {e}")
        return mentions
