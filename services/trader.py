import aiohttp
import random
import ccxt
from datetime import datetime
from config import settings
from database import Database

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.price_cache = {}
        self.exchange = self._init_exchange()
    
    def _init_exchange(self):
        if not settings.exchange_api_key:
            print("⚠️  Exchange not configured - paper trading only")
            return None
        
        try:
            exchange = ccxt.coinbase({
                'apiKey': settings.exchange_api_key,
                'secret': settings.exchange_api_secret,
            })
            print("✅ Coinbase exchange connected")
            return exchange
        except Exception as e:
            print(f"❌ Exchange init error: {e}")
            return None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_current_price(self, coin: str) -> float:
        if coin in self.price_cache:
            base_price = self.price_cache[coin]
            movement = random.uniform(-0.02, 0.02)
            return round(base_price * (1 + movement), 6)
        
        # Try exchange first
        if self.exchange:
            try:
                ticker = self.exchange.fetch_ticker(f"{coin}/USD")
                if ticker and ticker.get('last'):
                    self.price_cache[coin] = ticker['last']
                    return ticker['last']
            except:
                pass
        
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
        
        # Simulated for paper trading
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
            "AXS": "axie-infinity", "DAI": "dai", "SLP": "smooth-love-potion",
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
            if price == 0:
                continue
                
            quantity = settings.max_position_usd / price
            
            success = await self.buy(coin, quantity, price)
            if success:
                await self.db.open_position({
                    "coin": coin,
                    "quantity": quantity,
                    "buy_price": price,
                    "signal": signal
                })
            break
    
    async def buy(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER BUY: {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        
        if not self.exchange:
            print(f"📝 PAPER BUY (no exchange): {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        
        try:
            order = self.exchange.create_market_buy_order(f"{coin}/USD", quantity)
            print(f"🔥 LIVE BUY: {order}")
            return True
        except Exception as e:
            print(f"❌ Buy failed: {e}")
            return False
    
    async def sell(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER SELL: {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        
        if not self.exchange:
            print(f"📝 PAPER SELL (no exchange): {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        
        try:
            order = self.exchange.create_market_sell_order(f"{coin}/USD", quantity)
            print(f"🔥 LIVE SELL: {order}")
            return True
        except Exception as e:
            print(f"❌ Sell failed: {e}")
            return False
    
    async def check_exit_conditions(self):
        positions = await self.db.get_open_positions()
        
        for position in positions:
            coin = position["coin"]
            buy_price = position["buy_price"]
            quantity = position["quantity"]
            
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            if pnl_percent >= settings.take_profit_percent:
                print(f"🎯 TAKE PROFIT: {coin} @ {pnl_percent:+.1f}%")
                success = await self.sell(coin, quantity, current_price)
                if success:
                    await self.db.close_position(coin, current_price)
            elif pnl_percent <= -settings.stop_loss_percent:
                print(f"🛑 STOP LOSS: {coin} @ {pnl_percent:+.1f}%")
                success = await self.sell(coin, quantity, current_price)
                if success:
                    await self.db.close_position(coin, current_price)
            else:
                print(f"📊 Holding {coin}: {pnl_percent:+.1f}%")
