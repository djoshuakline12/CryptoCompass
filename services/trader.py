import ccxt
from datetime import datetime
from config import settings
from database import Database

class Trader:
    """Executes trades based on signals and manages positions"""
    
    def __init__(self, db: Database):
        self.db = db
        self.exchange = self._init_exchange()
    
    def _init_exchange(self):
        """Initialize exchange connection using ccxt"""
        if not settings.exchange_api_key:
            print("⚠️  Exchange not configured - paper trading only")
            return None
        
        exchange_class = getattr(ccxt, settings.exchange_name)
        return exchange_class({
            'apiKey': settings.exchange_api_key,
            'secret': settings.exchange_api_secret,
            'sandbox': not settings.live_trading,  # Use testnet if not live
        })
    
    async def get_current_price(self, coin: str) -> float:
        """Get current price for a coin"""
        symbol = f"{coin}/USDT"
        
        if self.exchange:
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                return ticker['last']
            except Exception as e:
                print(f"Error fetching price for {symbol}: {e}")
        
        # Fallback to CoinGecko if no exchange configured
        return await self._get_price_coingecko(coin)
    
    async def _get_price_coingecko(self, coin: str) -> float:
        """Fallback price fetcher using CoinGecko"""
        import aiohttp
        
        # Map common symbols to CoinGecko IDs
        coin_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "DOGE": "dogecoin", "SHIB": "shiba-inu", "PEPE": "pepe",
            "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2",
            "DOT": "polkadot", "LINK": "chainlink", "MATIC": "matic-network",
            "UNI": "uniswap", "ATOM": "cosmos", "LTC": "litecoin",
            "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
            "WIF": "dogwifcoin", "BONK": "bonk", "FLOKI": "floki",
        }
        
        coin_id = coin_ids.get(coin, coin.lower())
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": coin_id, "vs_currencies": "usd"}
                ) as resp:
                    data = await resp.json()
                    return data.get(coin_id, {}).get("usd", 0)
        except:
            return 0
    
    async def process_signals(self, signals: list[dict]):
        """Process signals and execute buy orders"""
        for signal in signals:
            coin = signal["coin"]
            
            # Skip if we already have a position
            if await self.db.has_open_position(coin):
                print(f"⏭️  Already holding {coin}, skipping")
                continue
            
            # Get current price
            price = await self.get_current_price(coin)
            if price == 0:
                print(f"❌ Could not get price for {coin}")
                continue
            
            # Calculate quantity
            quantity = settings.max_position_usd / price
            
            # Execute buy
            success = await self.buy(coin, quantity, price)
            
            if success:
                await self.db.open_position({
                    "coin": coin,
                    "quantity": quantity,
                    "buy_price": price,
                    "signal": signal
                })
                print(f"✅ Bought {quantity:.6f} {coin} at ${price:.4f}")
    
    async def buy(self, coin: str, quantity: float, price: float) -> bool:
        """Execute a buy order"""
        symbol = f"{coin}/USDT"
        
        if not settings.live_trading:
            print(f"📝 PAPER TRADE: Buy {quantity:.6f} {coin} at ${price:.4f}")
            return True
        
        if not self.exchange:
            return True  # Paper trade fallback
        
        try:
            order = self.exchange.create_market_buy_order(symbol, quantity)
            print(f"🔥 LIVE BUY: {order}")
            return True
        except Exception as e:
            print(f"❌ Buy failed: {e}")
            return False
    
    async def sell(self, coin: str, quantity: float, price: float) -> bool:
        """Execute a sell order"""
        symbol = f"{coin}/USDT"
        
        if not settings.live_trading:
            print(f"📝 PAPER TRADE: Sell {quantity:.6f} {coin} at ${price:.4f}")
            return True
        
        if not self.exchange:
            return True  # Paper trade fallback
        
        try:
            order = self.exchange.create_market_sell_order(symbol, quantity)
            print(f"🔥 LIVE SELL: {order}")
            return True
        except Exception as e:
            print(f"❌ Sell failed: {e}")
            return False
    
    async def check_exit_conditions(self):
        """Check all open positions for take profit / stop loss"""
        positions = await self.db.get_open_positions()
        
        for position in positions:
            coin = position["coin"]
            buy_price = position["buy_price"]
            quantity = position["quantity"]
            
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            # Check take profit
            if pnl_percent >= settings.take_profit_percent:
                print(f"🎯 Take profit triggered for {coin}: {pnl_percent:.1f}%")
                success = await self.sell(coin, quantity, current_price)
                if success:
                    trade = await self.db.close_position(coin, current_price)
                    print(f"✅ Sold {coin} for ${trade['pnl_usd']:.2f} profit")
            
            # Check stop loss
            elif pnl_percent <= -settings.stop_loss_percent:
                print(f"🛑 Stop loss triggered for {coin}: {pnl_percent:.1f}%")
                success = await self.sell(coin, quantity, current_price)
                if success:
                    trade = await self.db.close_position(coin, current_price)
                    print(f"❌ Sold {coin} for ${trade['pnl_usd']:.2f} loss")
