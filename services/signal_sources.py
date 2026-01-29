import aiohttp
import asyncio
from datetime import datetime, timezone

class SignalSources:
    def __init__(self):
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_all_signals(self) -> list:
        results = await asyncio.gather(
            self.get_dexscreener_trending(),
            self.get_dexscreener_boosted(),
            self.get_new_pairs(),
            return_exceptions=True
        )
        signals = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
        
        # Deduplicate by contract
        seen = {}
        for s in signals:
            contract = s.get("contract_address", "")
            if contract and contract not in seen:
                seen[contract] = s
        
        return list(seen.values())
    
    async def get_dexscreener_trending(self) -> list:
        """Get trending tokens with volume, filtered by our target range"""
        signals = []
        session = await self.get_session()
        
        try:
            # Search for active Solana pairs
            url = "https://api.dexscreener.com/latest/dex/pairs/solana?sort=volume&order=desc"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or data if isinstance(data, list) else []
                    
                    for pair in pairs[:100]:
                        if not pair:
                            continue
                        
                        mc = float(pair.get("fdv") or 0)
                        liq = float(pair.get("liquidity", {}).get("usd") or 0)
                        vol = float(pair.get("volume", {}).get("h24") or 0)
                        
                        # Filter to our target range: $500k-$50M MC, $100k+ liquidity
                        if 500000 <= mc <= 50000000 and liq >= 100000:
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            contract = pair.get("baseToken", {}).get("address", "")
                            
                            if symbol and contract:
                                change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                                signals.append({
                                    "coin": symbol.upper(),
                                    "contract_address": contract,
                                    "source": "dex_trending",
                                    "signal_score": 50 + min(int(change_1h), 30),
                                    "market_cap": mc,
                                    "liquidity": liq,
                                    "volume_24h": vol,
                                    "change_1h": change_1h,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except Exception as e:
            print(f"DexScreener trending error: {e}")
        
        return signals[:20]
    
    async def get_dexscreener_boosted(self) -> list:
        """Get boosted/promoted tokens"""
        signals = []
        session = await self.get_session()
        
        try:
            url = "https://api.dexscreener.com/token-boosts/top/v1"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for token in (data if isinstance(data, list) else [])[:30]:
                        if token.get("chainId") != "solana":
                            continue
                        
                        contract = token.get("tokenAddress", "")
                        if not contract:
                            continue
                        
                        # Get full details
                        detail_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
                        async with session.get(detail_url, timeout=aiohttp.ClientTimeout(total=10)) as detail_resp:
                            if detail_resp.status == 200:
                                detail = await detail_resp.json()
                                pairs = detail.get("pairs") or []
                                if pairs:
                                    pair = pairs[0]
                                    mc = float(pair.get("fdv") or 0)
                                    liq = float(pair.get("liquidity", {}).get("usd") or 0)
                                    
                                    if 500000 <= mc <= 50000000 and liq >= 100000:
                                        symbol = pair.get("baseToken", {}).get("symbol", "")
                                        signals.append({
                                            "coin": symbol.upper(),
                                            "contract_address": contract,
                                            "source": "dex_boosted",
                                            "signal_score": 65,
                                            "market_cap": mc,
                                            "liquidity": liq,
                                            "timestamp": datetime.now(timezone.utc).isoformat()
                                        })
        except Exception as e:
            print(f"DexScreener boosted error: {e}")
        
        return signals[:10]
    
    async def get_new_pairs(self) -> list:
        """Get newly created pairs (last 24h) in our range"""
        signals = []
        session = await self.get_session()
        
        try:
            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    
                    now = datetime.now(timezone.utc).timestamp() * 1000
                    
                    for pair in pairs[:50]:
                        created = pair.get("pairCreatedAt", 0)
                        if not created:
                            continue
                        
                        age_hours = (now - created) / (1000 * 60 * 60)
                        if age_hours > 48:  # Only last 48 hours
                            continue
                        
                        mc = float(pair.get("fdv") or 0)
                        liq = float(pair.get("liquidity", {}).get("usd") or 0)
                        
                        # Slightly looser for new pairs: $100k-$50M MC
                        if 100000 <= mc <= 50000000 and liq >= 50000:
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            contract = pair.get("baseToken", {}).get("address", "")
                            
                            if symbol and contract:
                                signals.append({
                                    "coin": symbol.upper(),
                                    "contract_address": contract,
                                    "source": "dex_new",
                                    "signal_score": 60,
                                    "market_cap": mc,
                                    "liquidity": liq,
                                    "age_hours": age_hours,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except Exception as e:
            print(f"New pairs error: {e}")
        
        return signals[:15]

signal_sources = SignalSources()
