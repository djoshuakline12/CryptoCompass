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
        results = await asyncio.gather(self.get_dexscreener_gainers(), return_exceptions=True)
        signals = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
        return signals
    
    async def get_dexscreener_gainers(self) -> list:
        signals = []
        session = await self.get_session()
        try:
            async with session.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for pair in (data.get("pairs") or [])[:50]:
                        if pair.get("chainId") == "solana":
                            symbol = pair.get("baseToken", {}).get("symbol", "")
                            contract = pair.get("baseToken", {}).get("address", "")
                            if symbol and contract:
                                signals.append({
                                    "coin": symbol.upper(),
                                    "contract_address": contract,
                                    "source": "dex_gainers",
                                    "signal_score": 50,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except:
            pass
        return signals

signal_sources = SignalSources()
