import asyncio
import aiohttp
import re
from typing import Optional
from config import settings
from datetime import datetime

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
            return float(settings.min_market_cap) <= mc <= float(settings.max_market_cap)
        except:
            return True
    
    async def scrape_all_sources(self) -> list[dict]:
        all_mentions = []
        results = await asyncio.gather(
            # Early discovery (highest priority)
            self.scrape_dexscreener_new_pairs(),
            self.scrape_geckoterminal_new_pools(),
            self.scrape_dexscreener_trending(),
            self.scrape_birdeye_trending(),
            self.scrape_dexscreener_volume_surge(),
            
            # Social monitoring
            self.scrape_twitter_via_nitter(),
            
            # Traditional sources
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
        print(f"📊 Total unique signals: {len(final)}")
        return final
    
    # ============ TWITTER/SOCIAL ============
    
    async def scrape_twitter_via_nitter(self) -> list[dict]:
        """Scrape crypto Twitter mentions via Nitter instances"""
        mentions = []
        session = await self.get_session()
        
        # Nitter instances (these change frequently)
        nitter_instances = [
            "https://nitter.privacydev.net",
            "https://nitter.poast.org",
            "https://nitter.1d4.us",
        ]
        
        # Search terms that precede pumps
        search_terms = [
            "100x gem crypto",
            "just launched token",
            "stealth launch crypto",
            "next 100x",
            "memecoin launch",
            "aping this"
        ]
        
        found_tickers = set()
        
        for instance in nitter_instances:
            if len(found_tickers) > 20:
                break
                
            for term in search_terms[:3]:  # Limit to avoid rate limits
                try:
                    url = f"{instance}/search?f=tweets&q={term.replace(' ', '+')}"
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=8),
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Extract $TICKER mentions
                            tickers = re.findall(r'\$([A-Z]{2,10})\b', text.upper())
                            
                            for ticker in tickers:
                                if ticker not in found_tickers and len(ticker) <= 8:
                                    # Skip common non-crypto tickers
                                    if ticker in ["USD", "BTC", "ETH", "USDT", "USDC", "THE", "FOR", "AND", "NOT"]:
                                        continue
                                    found_tickers.add(ticker)
                                    mentions.append({
                                        "coin": ticker,
                                        "source": "twitter",
                                        "count": 350,
                                        "market_cap": 0
                                    })
                                    print(f"🐦 TWITTER: ${ticker}")
                            
                            await asyncio.sleep(1)  # Rate limit
                except Exception as e:
                    continue
            
            if found_tickers:
                break  # Found working instance
        
        if not found_tickers:
            print("⚠️ Nitter: All instances down or blocked")
        
        return mentions
    
    # ============ EARLY DISCOVERY ============
    
    async def scrape_dexscreener_new_pairs(self) -> list[dict]:
        """Brand new trading pairs - earliest signal"""
        mentions = []
        session = await self.get_session()
        
        chains = ["solana", "base", "ethereum", "bsc", "arbitrum"]
        
        for chain in chains:
            try:
                async with session.get(
                    f"https://api.dexscreener.com/latest/dex/pairs/{chain}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    for pair in pairs[:100]:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        created_at = pair.get("pairCreatedAt", 0)
                        volume_24h = float(pair.get("volume", {}).get("h24") or 0)
                        liquidity = float(pair.get("liquidity", {}).get("usd") or 0)
                        price_change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        
                        if created_at:
                            age_hours = (datetime.now().timestamp() * 1000 - created_at) / (1000 * 60 * 60)
                        else:
                            age_hours = 999
                        
                        # NEW TOKENS (< 24h old)
                        if age_hours < 24 and volume_24h > 10000 and liquidity > 5000:
                            score = 500 + int(volume_24h / 1000)
                            mentions.append({
                                "coin": symbol,
                                "source": f"new_{chain}",
                                "count": min(score, 800),
                                "market_cap": fdv,
                                "age_hours": round(age_hours, 1)
                            })
                            print(f"🆕 NEW ({age_hours:.1f}h) {chain}: {symbol} vol=${volume_24h:,.0f}")
                        
                        # HOT MOMENTUM
                        elif price_change_5m > 10 and volume_24h > 50000 and liquidity > 20000:
                            if not self.passes_market_cap_filter(fdv):
                                continue
                            score = int(price_change_5m * 5 + volume_24h / 10000)
                            mentions.append({
                                "coin": symbol,
                                "source": f"hot_{chain}",
                                "count": min(score, 400),
                                "market_cap": fdv
                            })
                            print(f"🔥 HOT {chain}: {symbol} +{price_change_5m:.0f}% (5m)")
                            
            except Exception as e:
                print(f"DexScreener {chain} error: {e}")
        
        return mentions
    
    async def scrape_geckoterminal_new_pools(self) -> list[dict]:
        """GeckoTerminal new pools"""
        mentions = []
        session = await self.get_session()
        
        networks = ["solana", "base", "eth", "bsc"]
        
        for network in networks:
            try:
                async with session.get(
                    f"https://api.geckoterminal.com/api/v2/networks/{network}/new_pools",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    pools = data.get("data", [])
                    
                    for pool in pools[:20]:
                        attrs = pool.get("attributes", {})
                        name = attrs.get("name", "")
                        symbol = name.split("/")[0].upper() if "/" in name else name.upper()[:8]
                        volume_24h = float(attrs.get("volume_usd", {}).get("h24") or 0)
                        reserve = float(attrs.get("reserve_in_usd") or 0)
                        
                        if volume_24h > 5000 and reserve > 3000:
                            score = 450 + int(volume_24h / 2000)
                            mentions.append({
                                "coin": symbol[:10],
                                "source": f"gecko_{network}",
                                "count": min(score, 700),
                                "market_cap": 0
                            })
                            print(f"🌱 GECKO {network}: {symbol[:10]} vol=${volume_24h:,.0f}")
                            
            except Exception as e:
                print(f"GeckoTerminal {network} error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_trending(self) -> list[dict]:
        """DexScreener boosted/trending"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.dexscreener.com/token-boosts/top/v1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                tokens = await resp.json()
                
                for i, token in enumerate(tokens[:25] if isinstance(tokens, list) else []):
                    symbol = token.get("tokenSymbol", "").upper()
                    if symbol:
                        score = 350 - (i * 10)
                        mentions.append({
                            "coin": symbol,
                            "source": "dex_trend",
                            "count": max(score, 100),
                            "market_cap": 0
                        })
                        print(f"📈 DEX TREND: {symbol}")
                        
        except Exception as e:
            print(f"DexScreener trending error: {e}")
        
        return mentions
    
    async def scrape_birdeye_trending(self) -> list[dict]:
        """Birdeye Solana trending"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hChangePercent&sort_type=desc&offset=0&limit=30",
                headers={"x-chain": "solana"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return mentions
                data = await resp.json()
                tokens = data.get("data", {}).get("tokens", [])
                
                for token in tokens:
                    symbol = token.get("symbol", "").upper()
                    change_24h = float(token.get("v24hChangePercent") or 0)
                    volume = float(token.get("v24hUSD") or 0)
                    mc = float(token.get("mc") or 0)
                    
                    if change_24h > 20 and volume > 50000:
                        if not self.passes_market_cap_filter(mc):
                            continue
                        score = int(change_24h * 3 + volume / 20000)
                        mentions.append({
                            "coin": symbol,
                            "source": "birdeye",
                            "count": min(score, 400),
                            "market_cap": mc
                        })
                        print(f"🦅 BIRDEYE: {symbol} +{change_24h:.0f}%")
                        
        except Exception as e:
            print(f"Birdeye error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_volume_surge(self) -> list[dict]:
        """Sudden volume spikes"""
        mentions = []
        session = await self.get_session()
        
        try:
            async with session.get(
                "https://api.dexscreener.com/latest/dex/search?q=sol",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])[:50]
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        volume_5m = float(pair.get("volume", {}).get("m5") or 0)
                        volume_1h = float(pair.get("volume", {}).get("h1") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        
                        if volume_1h > 0 and volume_5m > volume_1h * 0.3:
                            if not self.passes_market_cap_filter(fdv):
                                continue
                            score = int(volume_5m / 1000 + 200)
                            mentions.append({
                                "coin": symbol,
                                "source": "vol_surge",
                                "count": min(score, 400),
                                "market_cap": fdv
                            })
                            print(f"📊 VOL SURGE: {symbol}")
                            
        except Exception as e:
            print(f"Volume surge error: {e}")
        
        return mentions
    
    # ============ TRADITIONAL SOURCES ============
    
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
                    try:
                        market_cap = float(str(item.get("data", {}).get("market_cap", "0")).replace(",", "").replace("$", "")) or 0
                    except:
                        market_cap = 0
                    
                    if not self.passes_market_cap_filter(market_cap):
                        continue
                    
                    score = (15 - i) * 15
                    if score > 0:
                        mentions.append({"coin": symbol, "source": "cg_trend", "count": score, "market_cap": market_cap})
        except Exception as e:
            print(f"CoinGecko trending error: {e}")
        return mentions
    
    async def scrape_coingecko_movers(self) -> list[dict]:
        mentions = []
        session = await self.get_session()
        try:
            for page in [2, 3]:
                async with session.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": "250", "page": str(page)},
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
                        
                        if change_24h > 15 and volume > 500000:
                            score = int(change_24h * 5)
                            mentions.append({"coin": symbol, "source": "cg_mover", "count": min(score, 300), "market_cap": market_cap})
        except Exception as e:
            print(f"CG movers error: {e}")
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
                        mentions.append({"coin": symbol, "source": "cmc_trend", "count": (15 - i) * 10, "market_cap": 0})
        except Exception as e:
            print(f"CMC trending error: {e}")
        return mentions
