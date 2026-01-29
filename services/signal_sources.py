import aiohttp
import asyncio
from datetime import datetime, timezone

class SignalSources:
    def __init__(self):
        self.session = None
        self.last_tokens = set()  # Track to avoid repeats
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_all_signals(self) -> list:
        results = await asyncio.gather(
            self.get_dexscreener_gainers(),
            self.get_dexscreener_new_pairs(),
            self.get_dexscreener_volume_leaders(),
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
        
        unique = list(seen.values())
        print(f"📊 {len(unique)} unique signals")
        return unique
    
    async def get_dexscreener_gainers(self) -> list:
        """Get top gainers in our market cap range"""
        signals = []
        session = await self.get_session()
        
        try:
            # Use token profiles for trending
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    solana_tokens = [t for t in data if t.get("chainId") == "solana"][:30]
                    
                    for token in solana_tokens:
                        contract = token.get("tokenAddress", "")
                        if not contract:
                            continue
                        
                        # Get full pair data
                        pair_data = await self._get_pair_data(contract)
                        if pair_data and self._is_valid_signal(pair_data):
                            signals.append(pair_data)
                            
        except Exception as e:
            print(f"Gainers error: {e}")
        
        return signals[:10]
    
    async def get_dexscreener_new_pairs(self) -> list:
        """Get newly created pairs with traction"""
        signals = []
        session = await self.get_session()
        
        try:
            # Search for recent Solana meme coins
            searches = ["solana meme", "sol pump", "new solana"]
            
            for search in searches:
                url = f"https://api.dexscreener.com/latest/dex/search?q={search}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        
                        for pair in pairs[:20]:
                            if pair.get("chainId") != "solana":
                                continue
                            
                            pair_data = self._parse_pair(pair)
                            if pair_data and self._is_valid_signal(pair_data):
                                signals.append(pair_data)
                                
        except Exception as e:
            print(f"New pairs error: {e}")
        
        return signals[:10]
    
    async def get_dexscreener_volume_leaders(self) -> list:
        """Get high volume tokens in our range"""
        signals = []
        session = await self.get_session()
        
        try:
            # Search specifically for smaller tokens
            searches = ["pump fun", "raydium new", "memecoin"]
            
            for search in searches:
                url = f"https://api.dexscreener.com/latest/dex/search?q={search}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        
                        for pair in pairs[:20]:
                            if pair.get("chainId") != "solana":
                                continue
                            
                            pair_data = self._parse_pair(pair)
                            if pair_data and self._is_valid_signal(pair_data):
                                signals.append(pair_data)
                                
        except Exception as e:
            print(f"Volume leaders error: {e}")
        
        return signals[:10]
    
    async def _get_pair_data(self, contract: str) -> dict:
        """Get detailed pair data for a token"""
        session = await self.get_session()
        
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    # Find best Solana pair
                    for pair in pairs:
                        if pair.get("chainId") == "solana":
                            return self._parse_pair(pair)
        except:
            pass
        
        return None
    
    def _parse_pair(self, pair: dict) -> dict:
        """Parse a DexScreener pair into our signal format"""
        try:
            mc = float(pair.get("fdv") or pair.get("marketCap") or 0)
            liq = float(pair.get("liquidity", {}).get("usd") or 0)
            vol = float(pair.get("volume", {}).get("h24") or 0)
            change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
            change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
            
            symbol = pair.get("baseToken", {}).get("symbol", "")
            contract = pair.get("baseToken", {}).get("address", "")
            
            if not symbol or not contract:
                return None
            
            txns = pair.get("txns", {})
            buys_1h = txns.get("h1", {}).get("buys", 0)
            sells_1h = txns.get("h1", {}).get("sells", 0)
            
            # Calculate signal score
            score = 50
            if 5 < change_1h < 30:
                score += 15
            if buys_1h > sells_1h:
                score += 10
            if vol > 100000:
                score += 10
            
            return {
                "coin": symbol.upper(),
                "contract_address": contract,
                "source": "dex_search",
                "signal_score": score,
                "market_cap": mc,
                "liquidity": liq,
                "volume_24h": vol,
                "change_1h": change_1h,
                "change_5m": change_5m,
                "buys_1h": buys_1h,
                "sells_1h": sells_1h,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except:
            return None
    
    def _is_valid_signal(self, signal: dict) -> bool:
        """Check if signal meets our criteria"""
        if not signal:
            return False
        
        mc = signal.get("market_cap", 0)
        liq = signal.get("liquidity", 0)
        vol = signal.get("volume_24h", 0)
        
        # Target range: $100k - $50M market cap
        if mc < 100000 or mc > 50000000:
            return False
        
        # Need some liquidity
        if liq < 30000:
            return False
        
        # Need some volume
        if vol < 10000:
            return False
        
        return True

signal_sources = SignalSources()
