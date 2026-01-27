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
        self.market_cap_cache = {}
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
    
    async def get_market_cap(self, coin: str) -> float:
        """Fetch market cap from CoinGecko or DexScreener"""
        if coin in self.market_cap_cache:
            return self.market_cap_cache[coin]
        
        session = await self.get_session()
        
        # Try CoinGecko search
        try:
            async with session.get(
                f"https://api.coingecko.com/api/v3/search?query={coin}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    coins = data.get("coins", [])
                    if coins:
                        coin_id = coins[0].get("id")
                        # Get market data
                        async with session.get(
                            f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                            params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as detail_resp:
                            if detail_resp.status == 200:
                                detail = await detail_resp.json()
                                mc = detail.get("market_data", {}).get("market_cap", {}).get("usd", 0)
                                if mc:
                                    self.market_cap_cache[coin] = mc
                                    return mc
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
                        fdv = float(pairs[0].get("fdv") or 0)
                        if fdv:
                            self.market_cap_cache[coin] = fdv
                            return fdv
        except:
            pass
        
        return 0
    
    async def get_current_price(self, coin: str) -> float:
        if coin in self.price_cache:
            base_price = self.price_cache[coin]
            movement = random.uniform(-0.02, 0.02)
            return round(base_price * (1 + movement), 6)
        
        session = await self.get_session()
        
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
        coin_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "DOGE": "dogecoin", "PEPE": "pepe", "XRP": "ripple",
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
                    price = float(data.get(coin_id, {}).get("usd", 0) or 0)
                    if price:
                        self.price_cache[coin] = price
                        return price
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
                        price = float(pairs[0].get("priceUsd", 0) or 0)
                        if price:
                            self.price_cache[coin] = price
                            return price
        except:
            pass
        
        # Simulated for paper trading
        simulated = round(random.uniform(0.01, 5.0), 4)
        self.price_cache[coin] = simulated
        return simulated
    
    def calculate_risk_score(self, signal: dict, market_cap: float) -> dict:
        """
        AI-based risk analysis
        Returns risk score (0-100) and recommended position size
        """
        risk_factors = []
        confidence_factors = []
        
        source = signal.get("source", "")
        score = signal.get("current_mentions", 0)
        age_hours = signal.get("age_hours", 999)
        
        # === RISK FACTORS (higher = more risky) ===
        
        # Market cap risk
        if market_cap == 0:
            risk_factors.append(("unknown_mcap", 30))
        elif market_cap < 10_000_000:  # < $10M
            risk_factors.append(("micro_cap", 25))
        elif market_cap < 50_000_000:  # < $50M
            risk_factors.append(("small_cap", 15))
        elif market_cap < 200_000_000:  # < $200M
            risk_factors.append(("mid_cap", 5))
        else:
            risk_factors.append(("large_cap", 0))
        
        # Token age risk
        if age_hours < 6:
            risk_factors.append(("very_new", 25))
        elif age_hours < 24:
            risk_factors.append(("new", 15))
        elif age_hours < 168:  # < 1 week
            risk_factors.append(("recent", 5))
        
        # Source reliability risk
        risky_sources = ["twitter", "telegram", "reddit"]
        safer_sources = ["cg_trend", "cg_mover", "cmc_trend"]
        if any(s in source for s in risky_sources):
            risk_factors.append(("social_source", 15))
        elif any(s in source for s in safer_sources):
            risk_factors.append(("established_source", 0))
        else:
            risk_factors.append(("dex_source", 10))
        
        # === CONFIDENCE FACTORS (higher = more confident) ===
        
        # Signal strength
        if score > 500:
            confidence_factors.append(("very_strong_signal", 25))
        elif score > 300:
            confidence_factors.append(("strong_signal", 15))
        elif score > 150:
            confidence_factors.append(("moderate_signal", 5))
        
        # Multiple source detection would add confidence
        # (TODO: track if coin appears from multiple sources)
        
        # Calculate scores
        total_risk = sum(f[1] for f in risk_factors)
        total_confidence = sum(f[1] for f in confidence_factors)
        
        # Risk score 0-100 (higher = riskier)
        risk_score = min(total_risk, 100)
        
        # Position size based on inverse risk
        # High risk = smaller position, Low risk = larger position
        risk_multiplier = (100 - risk_score) / 100  # 0.0 to 1.0
        confidence_multiplier = 1 + (total_confidence / 100)  # 1.0 to 1.5
        
        base_position = settings.total_portfolio_usd / settings.max_open_positions
        calculated_position = base_position * risk_multiplier * confidence_multiplier
        
        # Clamp to min/max
        position_size = max(settings.min_position_usd, min(calculated_position, settings.max_position_usd))
        
        return {
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "confidence_factors": confidence_factors,
            "recommended_position_usd": round(position_size, 2),
            "risk_level": "HIGH" if risk_score > 60 else "MEDIUM" if risk_score > 30 else "LOW"
        }
    
    async def process_signals(self, signals: list[dict]):
        if not settings.trading_enabled:
            print("⏸️ Trading disabled")
            return
        
        open_positions = await self.db.get_open_positions()
        if len(open_positions) >= settings.max_open_positions:
            print(f"📊 Max positions reached ({len(open_positions)}/{settings.max_open_positions})")
            return
        
        # Calculate how much capital is available
        used_capital = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in open_positions)
        available_capital = settings.total_portfolio_usd - used_capital
        
        for signal in signals[:5]:
            coin = signal["coin"]
            
            if await self.db.has_open_position(coin):
                continue
            
            price = await self.get_current_price(coin)
            if price == 0:
                continue
            
            # Get market cap for risk analysis
            market_cap = signal.get("market_cap", 0)
            if market_cap == 0:
                market_cap = await self.get_market_cap(coin)
            
            # AI position sizing
            if settings.use_ai_sizing:
                risk_analysis = self.calculate_risk_score(signal, market_cap)
                position_usd = min(risk_analysis["recommended_position_usd"], available_capital)
                
                print(f"🤖 AI ANALYSIS {coin}: {risk_analysis['risk_level']} risk ({risk_analysis['risk_score']}/100)")
                print(f"   Factors: {[f[0] for f in risk_analysis['risk_factors']]}")
                print(f"   Recommended: ${position_usd:.2f}")
            else:
                position_usd = min(settings.max_position_usd, available_capital)
            
            if position_usd < settings.min_position_usd:
                print(f"⚠️ Insufficient capital for {coin} (need ${settings.min_position_usd}, have ${position_usd:.2f})")
                continue
            
            quantity = position_usd / price
            
            success = await self.buy(coin, quantity, price)
            if success:
                await self.db.open_position({
                    "coin": coin,
                    "quantity": quantity,
                    "buy_price": price,
                    "position_usd": position_usd,
                    "market_cap": market_cap,
                    "risk_score": risk_analysis["risk_score"] if settings.use_ai_sizing else 50,
                    "signal": signal
                })
                available_capital -= position_usd
            
            # Only open one position per cycle to avoid rushing
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
