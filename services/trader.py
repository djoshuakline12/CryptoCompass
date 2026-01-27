import aiohttp
import random
from datetime import datetime
from config import settings
from database import Database

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.price_cache = {}
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_current_price(self, coin: str) -> float:
        # Check cache first
        if coin in self.price_cache:
            base_price = self.price_cache[coin]
            # Add small random movement
            movement = random.uniform(-0.02, 0.02)
            return round(base_price * (1 + movement), 6)
        
        # Try CoinGecko
        price = await self._get_price_coingecko(coin)
        if price > 0:
            self.price_cache[coin] = price
            return price
        
        # Try DexScreener
        price = await self._get_price_dexscreener(coin)
        if price > 0:
            self.price_cache[coin] = price
            return price
        
        # Generate simulated price for paper trading
        simulated = round(random.uniform(0.01, 5.0), 4)
        self.price_cache[coin] = simulated
        print(f"💵 Simulated price for {coin}: ${simulated}")
        return simulated
    
    async def _get_price_coingecko(self, coin: str) -> float:
        session = await self.get_session()
        coin_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "DOGE": "dogecoin", "PEPE": "pepe", "XRP": "ripple",
            "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
            "LINK": "chainlink", "WIF": "dogwifhat", "BONK": "bonk",
            "PENGU": "pudgy-penguins", "AXS": "axie-infinity",
            "DAI": "dai", "SLP": "smooth-love-potion", "RON": "ronin",
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
                    return float(data.get(coin_id, {}).get("usd", 0) or 0)
        except:
            pass
        return 0
    
    async def _get_price_dexscreener(self, coin: str) -> float:
        session = await self.get_session()
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
    
    async def process_signals(self, signals: list[dict]):
        if not settings.trading_enabled:
            print("⏸️ Trading disabled")
            return
        
        open_positions = await self.db.get_open_positions()
        if len(open_positions) >= 3:
            print(f"📊 Max positions reached ({len(open_positions)}/3)")
            return
        
        for signal in signals[:3]:
            coin = signal["coin"]
            
            if await self.db.has_open_position(coin):
                continue
            
            price = await self.get_current_price(coin)
            quantity = settings.max_position_usd / price
            
            print(f"✅ PAPER BUY: {quantity:.4f} {coin} @ ${price:.4f} (${settings.max_position_usd})")
            
            await self.db.open_position({
                "coin": coin,
                "quantity": quantity,
                "buy_price": price,
                "signal": signal
            })
            
            # Only open one position per cycle
            break
    
    async def check_exit_conditions(self):
        positions = await self.db.get_open_positions()
        
        for position in positions:
            coin = position["coin"]
            buy_price = position["buy_price"]
            quantity = position["quantity"]
            
            current_price = await self.get_current_price(coin)
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            if pnl_percent >= settings.take_profit_percent:
                print(f"🎯 TAKE PROFIT: {coin} @ {pnl_percent:+.1f}%")
                await self.db.close_position(coin, current_price)
            elif pnl_percent <= -settings.stop_loss_percent:
                print(f"🛑 STOP LOSS: {coin} @ {pnl_percent:+.1f}%")
                await self.db.close_position(coin, current_price)
            else:
                print(f"📊 Holding {coin}: {pnl_percent:+.1f}% (${current_price:.4f})")
