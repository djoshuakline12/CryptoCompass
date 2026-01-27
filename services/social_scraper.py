import asyncio
import aiohttp
import re
from datetime import datetime, timezone
from config import settings

class SocialScraper:
    def __init__(self):
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def passes_mcap_filter(self, mc):
        try:
            mc = float(mc or 0)
            if mc == 0:
                return True
            return settings.min_market_cap <= mc <= settings.max_market_cap
        except:
            return True
    
    async def scrape_all_sources(self) -> list:
        results = await asyncio.gather(
            self.scrape_dexscreener_new(),
            self.scrape_dexscreener_trending(),
            self.scrape_geckoterminal(),
            self.scrape_birdeye(),
            self.scrape_reddit(),
            return_exceptions=True
        )
        
        all_mentions = []
        for r in results:
            if isinstance(r, list):
                all_mentions.extend(r)
        
        seen = {}
        for m in all_mentions:
            coin = m["coin"]
            if coin not in seen or m["count"] > seen[coin]["count"]:
                seen[coin] = m
        
        final = list(seen.values())
        print(f"📊 {len(final)} unique signals")
        return final
    
    async def scrape_dexscreener_new(self) -> list:
        mentions = []
        session = await self.get_session()
        
        for chain in ["solana", "base", "ethereum"]:
            try:
                async with session.get(f"https://api.dexscreener.com/latest/dex/pairs/{chain}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    
                    for pair in data.get("pairs", [])[:50]:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        created = pair.get("pairCreatedAt", 0)
                        volume = float(pair.get("volume", {}).get("h24") or 0)
                        liquidity = float(pair.get("liquidity", {}).get("usd") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        
                        age_hours = (datetime.now(timezone.utc).timestamp() * 1000 - created) / (1000 * 60 * 60) if created else 999
                        
                        if age_hours < 24 and volume > 10000 and liquidity > 5000:
                            mentions.append({
                                "coin": symbol,
                                "source": f"new_{chain}",
                                "count": min(500 + int(volume / 1000), 800),
                                "market_cap": fdv,
                                "age_hours": round(age_hours, 1)
                            })
            except:
                pass
        
        return mentions
    
    async def scrape_dexscreener_trending(self) -> list:
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    tokens = await resp.json()
                    for i, token in enumerate(tokens[:20] if isinstance(tokens, list) else []):
                        symbol = token.get("tokenSymbol", "").upper()
                        if symbol:
                            mentions.append({
                                "coin": symbol,
                                "source": "dex_trending",
                                "count": 350 - (i * 10),
                                "market_cap": 0
                            })
        except:
            pass
        
        return mentions
    
    async def scrape_geckoterminal(self) -> list:
        mentions = []
        session = await self.get_session()
        
        for network in ["solana", "base", "eth"]:
            try:
                async with session.get(f"https://api.geckoterminal.com/api/v2/networks/{network}/new_pools", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    
                    for pool in data.get("data", [])[:15]:
                        attrs = pool.get("attributes", {})
                        name = attrs.get("name", "")
                        symbol = name.split("/")[0].upper()[:8] if "/" in name else name.upper()[:8]
                        volume = float(attrs.get("volume_usd", {}).get("h24") or 0)
                        
                        if volume > 5000:
                            mentions.append({
                                "coin": symbol,
                                "source": f"gecko_{network}",
                                "count": min(400 + int(volume / 2000), 600),
                                "market_cap": 0
                            })
            except:
                pass
        
        return mentions
    
    async def scrape_birdeye(self) -> list:
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hChangePercent&sort_type=desc&offset=0&limit=20",
                headers={"x-chain": "solana"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for token in data.get("data", {}).get("tokens", []):
                        symbol = token.get("symbol", "").upper()
                        change = float(token.get("v24hChangePercent") or 0)
                        volume = float(token.get("v24hUSD") or 0)
                        mc = float(token.get("mc") or 0)
                        
                        if change > 20 and volume > 50000 and self.passes_mcap_filter(mc):
                            mentions.append({
                                "coin": symbol,
                                "source": "birdeye",
                                "count": min(int(change * 3), 400),
                                "market_cap": mc
                            })
        except:
            pass
        
        return mentions
    
    async def scrape_reddit(self) -> list:
        mentions = []
        session = await self.get_session()
        found = {}
        
        for sub in ["cryptomoonshots", "wallstreetbetscrypto", "SatoshiStreetBets"]:
            try:
                async with session.get(
                    f"https://www.reddit.com/r/{sub}/new.json?limit=30",
                    headers={"User-Agent": "CryptoBuzzBot/1.0"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    
                    for post in data.get("data", {}).get("children", []):
                        pd = post.get("data", {})
                        text = f"{pd.get('title', '')} {pd.get('selftext', '')}".upper()
                        score = pd.get("score", 0)
                        
                        for ticker in re.findall(r'\$([A-Z]{2,10})\b', text):
                            if ticker in ["USD", "USDT", "USDC", "BTC", "ETH", "SOL", "BNB"]:
                                continue
                            weight = min(score + 10, 100)
                            if ticker in found:
                                found[ticker] += int(weight)
                            else:
                                found[ticker] = int(weight)
                
                await asyncio.sleep(0.5)
            except:
                pass
        
        for ticker, count in found.items():
            if count >= 30:
                mentions.append({
                    "coin": ticker,
                    "source": "reddit",
                    "count": min(count, 400),
                    "market_cap": 0
                })
        
        return mentions
