from datetime import datetime
from config import settings
from database import Database
import aiohttp

class AnomalyDetector:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_price(self, coin: str) -> float:
        session = await self.get_session()
        
        # Try CoinGecko
        coin_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "AXS": "axie-infinity", "DAI": "dai", "SLP": "smooth-love-potion",
            "RON": "ronin", "PENGU": "pudgy-penguins", "PEPE": "pepe",
        }
        coin_id = coin_ids.get(coin, coin.lower())
        
        try:
            async with session.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get(coin_id, {}).get("usd", 0)
                    if price:
                        return float(price)
        except:
            pass
        
        # Try DexScreener
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return float(pairs[0].get("priceUsd", 0) or 0)
        except:
            pass
        
        return 0
    
    async def detect_signals(self) -> list[dict]:
        signals = []
        
        all_mentions = await self.db.get_all_recent_mentions()
        
        coin_data = {}
        for mention in all_mentions:
            coin = mention.get("coin", "")
            count = mention.get("count", 0)
            market_cap = mention.get("market_cap", 0)
            change_24h = mention.get("change_24h", 0)
            
            if coin:
                if coin not in coin_data:
                    coin_data[coin] = {"score": 0, "market_cap": market_cap, "change_24h": change_24h}
                coin_data[coin]["score"] += count
                if market_cap and market_cap > 0:
                    coin_data[coin]["market_cap"] = market_cap
                if change_24h and change_24h > 0:
                    coin_data[coin]["change_24h"] = change_24h
        
        sorted_coins = sorted(coin_data.items(), key=lambda x: x[1]["score"], reverse=True)
        
        for coin, data in sorted_coins[:10]:
            if data["score"] >= 50:
                # Fetch current price
                price = await self.get_price(coin)
                
                signal = {
                    "coin": coin,
                    "current_mentions": data["score"],
                    "baseline_mentions": 0,
                    "percent_above_baseline": data["score"],
                    "threshold": settings.buzz_threshold,
                    "market_cap": data["market_cap"],
                    "change_24h": data.get("change_24h", 0),
                    "price_at_signal": price,
                    "current_price": price
                }
                signals.append(signal)
                await self.db.save_signal(signal)
                
                if price > 0:
                    print(f"🚨 SIGNAL: {coin} @ ${price:.4f} (mcap: ${data['market_cap']:,.0f})")
                else:
                    print(f"🚨 SIGNAL: {coin} (no price) (mcap: ${data['market_cap']:,.0f})")
        
        return signals
