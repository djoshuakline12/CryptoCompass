import asyncio
import aiohttp
from typing import Optional
from config import settings
from datetime import datetime, timedelta

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
            # Early discovery sources (highest priority)
            self.scrape_dexscreener_new_pairs(),
            self.scrape_geckoterminal_new_pools(),
            self.scrape_dexscreener_trending(),
            self.scrape_birdeye_trending(),
            
            # Volume/momentum sources
            self.scrape_dexscreener_volume_surge(),
            self.scrape_coingecko_movers(),
            
            # Social/search trending (lagging but useful)
            self.scrape_coingecko_trending(),
            self.scrape_coinmarketcap_trending(),
            
            return_exceptions=True
        )
        for result in results:
            if isinstance(result, list):
                all_mentions.extend(result)
            elif isinstance(result, Exception):
                print(f"Scraper error: {result}")
        
        # Remove duplicates, prioritize highest scores
        seen = {}
        for m in all_mentions:
            coin = m["coin"]
            if coin not in seen or m["count"] > seen[coin]["count"]:
                seen[coin] = m
        
        final = list(seen.values())
        print(f"📊 Total unique signals: {len(final)}")
        return final
    
    # ============ EARLY DISCOVERY SOURCES ============
    
    async def scrape_dexscreener_new_pairs(self) -> list[dict]:
        """Find brand new trading pairs - earliest possible signal"""
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
                        price_change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        txns = pair.get("txns", {}).get("h24", {})
                        buys = txns.get("buys", 0)
                        sells = txns.get("sells", 0)
                        
                        # Calculate age in hours
                        if created_at:
                            age_hours = (datetime.now().timestamp() * 1000 - created_at) / (1000 * 60 * 60)
                        else:
                            age_hours = 999
                        
                        # NEW TOKEN CRITERIA (< 24 hours old)
                        if age_hours < 24:
                            if volume_24h > 10000 and liquidity > 5000:
                                score = 500 + int(volume_24h / 1000)  # High base score for new tokens
                                mentions.append({
                                    "coin": symbol,
                                    "source": f"new_pair_{chain}",
                                    "count": min(score, 800),
                                    "market_cap": fdv,
                                    "age_hours": round(age_hours, 1),
                                    "volume_24h": volume_24h,
                                    "liquidity": liquidity
                                })
                                print(f"🆕 NEW ({age_hours:.1f}h) {chain}: {symbol} vol=${volume_24h:,.0f} liq=${liquidity:,.0f}")
                        
                        # HOT MOMENTUM (any age, but moving fast)
                        elif price_change_5m > 10 and volume_24h > 50000 and liquidity > 20000:
                            if not self.passes_market_cap_filter(fdv):
                                continue
                            score = int(price_change_5m * 5 + volume_24h / 10000)
                            mentions.append({
                                "coin": symbol,
                                "source": f"hot_{chain}",
                                "count": min(score, 400),
                                "market_cap": fdv,
                                "change_5m": price_change_5m
                            })
                            print(f"🔥 HOT {chain}: {symbol} +{price_change_5m:.0f}% (5m)")
                            
            except Exception as e:
                print(f"DexScreener {chain} error: {e}")
        
        return mentions
    
    async def scrape_geckoterminal_new_pools(self) -> list[dict]:
        """GeckoTerminal new pools - catches tokens at launch"""
        mentions = []
        session = await self.get_session()
        
        networks = ["solana", "base", "eth", "bsc", "arbitrum"]
        
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
                    
                    for pool in pools[:30]:
                        attrs = pool.get("attributes", {})
                        name = attrs.get("name", "")
                        symbol = name.split("/")[0].upper() if "/" in name else name.upper()
                        volume_24h = float(attrs.get("volume_usd", {}).get("h24") or 0)
                        reserve = float(attrs.get("reserve_in_usd") or 0)
                        created = attrs.get("pool_created_at", "")
                        
                        if volume_24h > 5000 and reserve > 3000:
                            score = 450 + int(volume_24h / 2000)
                            mentions.append({
                                "coin": symbol[:10],  # Truncate long names
                                "source": f"gecko_new_{network}",
                                "count": min(score, 700),
                                "market_cap": 0,
                                "volume_24h": volume_24h
                            })
                            print(f"🌱 GECKO NEW {network}: {symbol[:10]} vol=${volume_24h:,.0f}")
                            
            except Exception as e:
                print(f"GeckoTerminal {network} error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_trending(self) -> list[dict]:
        """DexScreener trending tokens"""
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
                            "source": "dex_trending",
                            "count": max(score, 100),
                            "market_cap": 0
                        })
                        print(f"📈 DEX TREND #{i+1}: {symbol}")
                        
        except Exception as e:
            print(f"DexScreener trending error: {e}")
        
        return mentions
    
    async def scrape_birdeye_trending(self) -> list[dict]:
        """Birdeye Solana trending - catches Solana memecoins early"""
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
                            "source": "birdeye_sol",
                            "count": min(score, 400),
                            "market_cap": mc,
                            "change_24h": change_24h
                        })
                        print(f"🦅 BIRDEYE: {symbol} +{change_24h:.0f}%")
                        
        except Exception as e:
            print(f"Birdeye error: {e}")
        
        return mentions
    
    async def scrape_dexscreener_volume_surge(self) -> list[dict]:
        """Find tokens with sudden volume spikes"""
        mentions = []
        session = await self.get_session()
        
        try:
            # Search for high volume across all chains
            async with session.get(
                "https://api.dexscreener.com/latest/dex/search?q=sol",  # Solana tokens
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])[:50]
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        volume_5m = float(pair.get("volume", {}).get("m5") or 0)
                        volume_1h = float(pair.get("volume", {}).get("h1") or 0)
                        volume_24h = float(pair.get("volume", {}).get("h24") or 0)
                        fdv = float(pair.get("fdv") or 0)
                        
                        # Volume surge detection (5m volume > 10% of hourly)
                        if volume_1h > 0 and volume_5m > volume_1h * 0.3:
                            if not self.passes_market_cap_filter(fdv):
                                continue
                            score = int(volume_5m / 1000 + 200)
                            mentions.append({
                                "coin": symbol,
                                "source": "volume_surge",
                                "count": min(score, 400),
                                "market_cap": fdv
                            })
                            print(f"📊 VOL SURGE: {symbol} 5m=${volume_5m:,.0f}")
                            
        except Exception as e:
            print(f"Volume surge error: {e}")
        
        return mentions
    
    # ============ EXISTING SOURCES (kept for breadth) ============
    
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
                    
                    score = (15 - i) * 15
                    if score > 0:
                        mentions.append({
                            "coin": symbol,
                            "source": "cg_trending",
                            "count": score,
                            "market_cap": market_cap
                        })
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
                        
                        if change_24h > 15 and volume > 500_000:
                            score = int(change_24h * 5)
                            mentions.append({
                                "coin": symbol,
                                "source": "cg_mover",
                                "count": min(score, 300),
                                "market_cap": market_cap,
                                "change_24h": round(change_24h, 1)
                            })
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
                        score = (15 - i) * 10
                        mentions.append({"coin": symbol, "source": "cmc_trending", "count": score, "market_cap": 0})
        except Exception as e:
            print(f"CMC trending error: {e}")
        return mentions
