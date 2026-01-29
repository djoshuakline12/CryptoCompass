import aiohttp

class VolumeDetector:
    def __init__(self):
        self.spike_threshold = 3.0
    
    async def check_volume_spike(self, contract_address: str) -> dict:
        result = {"has_spike": False, "current_volume_5m": 0, "avg_volume_5m": 0, "spike_multiplier": 1.0}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            pair = pairs[0]
                            vol_5m = float(pair.get("volume", {}).get("m5") or 0)
                            vol_1h = float(pair.get("volume", {}).get("h1") or 0)
                            avg_5m = vol_1h / 12 if vol_1h > 0 else 0
                            result["current_volume_5m"] = vol_5m
                            result["avg_volume_5m"] = avg_5m
                            if avg_5m > 0:
                                mult = vol_5m / avg_5m
                                result["spike_multiplier"] = round(mult, 2)
                                result["has_spike"] = mult >= self.spike_threshold
        except:
            pass
        return result

volume_detector = VolumeDetector()
