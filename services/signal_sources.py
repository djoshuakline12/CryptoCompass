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
            self.get_dexscreener_gainers(),
            self.get_new_pairs(),
            return_exceptions=True
        )
        signals = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
        
        # Deduplicate
        seen = {}
        for s in signals:
            contract = s.get("contract_address", "")
            if contract and contract not in seen:
                seen[contract] = s
        
        return list(seen.values())
    
    async def get_dexscreener_gainers(self) -> list:
        """Get coins with real momentum (not paid promotion)"""
        signals = []
        session = await self.get_session()
        
        try:
            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    
                    for pair in pairs[:100]:
                        mc = float(pair.get("fdv") or 0)
                        liq = float(pair.get("liquidity", {}).get("usd") or 0)
                        vol = float(pair.get("volume", {}).get("h24") or 0)
                        change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                        change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
                        
                        # Require REAL momentum: +5% to +25% in last hour
                        # But NOT already pumped too much in 5m (FOMO trap)
                        if (500000 <= mc <= 50000000 and 
                            liq >= 100000 and
                            5 <= change_1h <= 25 and
                            change_5m < 10 and change_5m > -5):  # Not dumping or mooning
                            
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            contract = pair.get("baseToken", {}).get("address", "")
                            
                            # Require good volume
                            if symbol and contract and vol > 50000:
                                txns = pair.get("txns", {}).get("h1", {})
                                buys = txns.get("buys", 0)
                                sells = txns.get("sells", 0)
                                
                                # Require more buys than sells
                                if buys > sells and (buys + sells) > 20:
                                    signals.append({
                                        "coin": symbol.upper(),
                                        "contract_address": contract,
                                        "source": "dex_momentum",
                                        "signal_score": 50 + int(change_1h),
                                        "market_cap": mc,
                                        "liquidity": liq,
                                        "volume_24h": vol,
                                        "change_1h": change_1h,
                                        "change_5m": change_5m,
                                        "buy_sell_ratio": buys / max(sells, 1),
                                        "timestamp": datetime.now(timezone.utc).isoformat()
                                    })
        except Exception as e:
            print(f"DexScreener error: {e}")
        
        # Sort by momentum
        signals.sort(key=lambda x: x.get("change_1h", 0), reverse=True)
        return signals[:15]
    
    async def get_new_pairs(self) -> list:
        """Get new pairs with traction"""
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
                        if not (2 <= age_hours <= 24):  # 2-24 hours old
                            continue
                        
                        mc = float(pair.get("fdv") or 0)
                        liq = float(pair.get("liquidity", {}).get("usd") or 0)
                        vol = float(pair.get("volume", {}).get("h24") or 0)
                        change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                        
                        if (200000 <= mc <= 20000000 and 
                            liq >= 75000 and
                            vol >= 30000 and
                            change_1h > 0):  # Must be green
                            
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            contract = pair.get("baseToken", {}).get("address", "")
                            
                            if symbol and contract:
                                signals.append({
                                    "coin": symbol.upper(),
                                    "contract_address": contract,
                                    "source": "dex_new",
                                    "signal_score": 55,
                                    "market_cap": mc,
                                    "liquidity": liq,
                                    "age_hours": age_hours,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except Exception as e:
            print(f"New pairs error: {e}")
        
        return signals[:10]

signal_sources = SignalSources()
