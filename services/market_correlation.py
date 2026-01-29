import aiohttp
from datetime import datetime, timezone

class MarketCorrelation:
    def __init__(self):
        self.btc_data = None
        self.sol_data = None
        self.last_check = None
    
    async def check_market_conditions(self) -> dict:
        if self.last_check and (datetime.now(timezone.utc) - self.last_check).seconds < 60:
            return self._get_result()
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.btc_data = {"change_24h": data.get("bitcoin", {}).get("usd_24h_change", 0)}
                        self.sol_data = {"change_24h": data.get("solana", {}).get("usd_24h_change", 0), "change_1h": 0}
                        self.last_check = datetime.now(timezone.utc)
        except:
            pass
        return self._get_result()
    
    def _get_result(self) -> dict:
        result = {"safe_to_buy": True, "btc_change_24h": 0, "sol_change_24h": 0, "sol_change_1h": 0, "warning": None}
        if self.btc_data:
            result["btc_change_24h"] = self.btc_data.get("change_24h", 0)
        if self.sol_data:
            result["sol_change_24h"] = self.sol_data.get("change_24h", 0)
            result["sol_change_1h"] = self.sol_data.get("change_1h", 0)
        if result["sol_change_1h"] < -3:
            result["safe_to_buy"] = False
            result["warning"] = f"SOL dumping {result['sol_change_1h']:.1f}%"
        if result["btc_change_24h"] < -5:
            result["safe_to_buy"] = False
            result["warning"] = f"BTC down {result['btc_change_24h']:.1f}%"
        return result

market_correlation = MarketCorrelation()
