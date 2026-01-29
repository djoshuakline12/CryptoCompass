import aiohttp
from datetime import datetime, timezone

class PumpFunScanner:
    def __init__(self):
        self.seen_tokens = set()
    
    async def get_all_signals(self) -> list:
        signals = []
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://frontend-api.pump.fun/coins?offset=0&limit=30&sort=created_timestamp&order=desc"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for token in data:
                            mint = token.get("mint", "")
                            if not mint or mint in self.seen_tokens:
                                continue
                            self.seen_tokens.add(mint)
                            market_cap = float(token.get("usd_market_cap") or 0)
                            created = token.get("created_timestamp", 0)
                            age_min = (datetime.now(timezone.utc).timestamp() - created / 1000) / 60 if created else 999
                            if 5 < age_min < 60 and market_cap > 5000:
                                signals.append({
                                    "coin": token.get("symbol", "").upper(),
                                    "contract_address": mint,
                                    "source": "pumpfun_new",
                                    "signal_score": 70,
                                    "market_cap": market_cap,
                                    "age_minutes": age_min,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
        except Exception as e:
            print(f"Pump.fun error: {e}")
        return signals

pumpfun_scanner = PumpFunScanner()
