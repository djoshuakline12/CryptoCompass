import aiohttp
import random
import ccxt
from datetime import datetime, timedelta
from config import settings
from database import Database

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.price_cache = {}
        self.market_cap_cache = {}
        self.price_history = {}  # Track price over time for momentum
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
        if coin in self.market_cap_cache:
            return self.market_cap_cache[coin]
        
        session = await self.get_session()
        
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
        session = await self.get_session()
        
        # Always fetch fresh price for accuracy
        price = 0
        
        # Try exchange first
        if self.exchange:
            try:
                ticker = self.exchange.fetch_ticker(f"{coin}/USD")
                if ticker and ticker.get('last'):
                    price = ticker['last']
            except:
                pass
        
        # Try CoinGecko
        if price == 0:
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
            except:
                pass
        
        # Try DexScreener
        if price == 0:
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
            except:
                pass
        
        # Simulated fallback
        if price == 0:
            if coin in self.price_cache:
                price = self.price_cache[coin] * (1 + random.uniform(-0.02, 0.02))
            else:
                price = round(random.uniform(0.01, 5.0), 4)
        
        # Track price history for momentum analysis
        self.price_cache[coin] = price
        if coin not in self.price_history:
            self.price_history[coin] = []
        self.price_history[coin].append({
            "price": price,
            "timestamp": datetime.utcnow()
        })
        # Keep last 30 data points
        self.price_history[coin] = self.price_history[coin][-30:]
        
        return price
    
    async def get_token_momentum(self, coin: str) -> dict:
        """
        Analyze token momentum using price history and on-chain data
        Returns prediction of future movement
        """
        session = await self.get_session()
        
        momentum = {
            "trend": "neutral",  # up, down, neutral
            "strength": 0,  # -100 to 100
            "volatility": 0,
            "volume_trend": "stable",
            "predicted_upside": 0,  # percentage
            "confidence": 0,  # 0-100
            "should_sell": False,
            "reason": ""
        }
        
        # === Price Momentum Analysis ===
        history = self.price_history.get(coin, [])
        if len(history) >= 3:
            prices = [h["price"] for h in history]
            
            # Calculate recent trend (last 5 vs previous 5)
            if len(prices) >= 10:
                recent_avg = sum(prices[-5:]) / 5
                previous_avg = sum(prices[-10:-5]) / 5
                price_momentum = ((recent_avg - previous_avg) / previous_avg) * 100
            else:
                recent = prices[-1]
                oldest = prices[0]
                price_momentum = ((recent - oldest) / oldest) * 100
            
            momentum["strength"] = round(price_momentum, 2)
            
            if price_momentum > 2:
                momentum["trend"] = "up"
            elif price_momentum < -2:
                momentum["trend"] = "down"
            
            # Calculate volatility
            if len(prices) >= 5:
                avg = sum(prices) / len(prices)
                variance = sum((p - avg) ** 2 for p in prices) / len(prices)
                momentum["volatility"] = round((variance ** 0.5) / avg * 100, 2)
        
        # === On-chain / DEX Data Analysis ===
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        pair = pairs[0]
                        
                        # Price changes at different timeframes
                        change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
                        change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                        change_6h = float(pair.get("priceChange", {}).get("h6") or 0)
                        change_24h = float(pair.get("priceChange", {}).get("h24") or 0)
                        
                        # Volume analysis
                        vol_5m = float(pair.get("volume", {}).get("m5") or 0)
                        vol_1h = float(pair.get("volume", {}).get("h1") or 0)
                        vol_6h = float(pair.get("volume", {}).get("h6") or 0)
                        vol_24h = float(pair.get("volume", {}).get("h24") or 0)
                        
                        # Buy/Sell pressure
                        txns = pair.get("txns", {})
                        buys_24h = txns.get("h24", {}).get("buys", 0)
                        sells_24h = txns.get("h24", {}).get("sells", 0)
                        buys_1h = txns.get("h1", {}).get("buys", 0)
                        sells_1h = txns.get("h1", {}).get("sells", 0)
                        
                        # === Momentum Signals ===
                        
                        # 1. Slowing momentum (was going up, now slowing)
                        if change_24h > 20 and change_1h < 2 and change_5m < 0:
                            momentum["trend"] = "down"
                            momentum["reason"] = "Momentum slowing after big run"
                            momentum["predicted_upside"] = -5
                        
                        # 2. Volume dying (price up but volume dropping)
                        if vol_1h > 0 and vol_6h > 0:
                            vol_ratio = (vol_1h * 6) / vol_6h if vol_6h > 0 else 1
                            if vol_ratio < 0.5 and change_24h > 10:
                                momentum["volume_trend"] = "declining"
                                momentum["reason"] = "Volume declining, rally losing steam"
                                momentum["predicted_upside"] = max(momentum["predicted_upside"] - 10, -20)
                        
                        # 3. Sell pressure increasing
                        if sells_1h > buys_1h * 1.5:
                            momentum["reason"] = "Heavy sell pressure"
                            momentum["predicted_upside"] -= 10
                        elif buys_1h > sells_1h * 1.5:
                            momentum["predicted_upside"] += 10
                        
                        # 4. Strong continued momentum
                        if change_5m > 5 and change_1h > 10 and buys_1h > sells_1h:
                            momentum["trend"] = "up"
                            momentum["predicted_upside"] = min(change_1h * 0.5, 30)
                            momentum["reason"] = "Strong buying momentum"
                        
                        # 5. Already pumped hard (diminishing returns)
                        if change_24h > 50:
                            momentum["predicted_upside"] = min(momentum["predicted_upside"], 10)
                            if change_1h < 5:
                                momentum["reason"] = "Already pumped significantly, limited upside"
                        
                        # Calculate confidence
                        data_points = sum([
                            1 if vol_24h > 0 else 0,
                            1 if buys_24h > 0 else 0,
                            len(history) >= 5,
                            1 if change_24h != 0 else 0
                        ])
                        momentum["confidence"] = data_points * 25
                        
        except Exception as e:
            print(f"Momentum analysis error for {coin}: {e}")
        
        return momentum
    
    def calculate_risk_score(self, signal: dict, market_cap: float) -> dict:
        """AI-based risk analysis"""
        risk_factors = []
        confidence_factors = []
        
        source = signal.get("source", "")
        score = signal.get("current_mentions", 0)
        age_hours = signal.get("age_hours", 999)
        
        # Market cap risk
        if market_cap == 0:
            risk_factors.append(("unknown_mcap", 30))
        elif market_cap < 10_000_000:
            risk_factors.append(("micro_cap", 25))
        elif market_cap < 50_000_000:
            risk_factors.append(("small_cap", 15))
        elif market_cap < 200_000_000:
            risk_factors.append(("mid_cap", 5))
        else:
            risk_factors.append(("large_cap", 0))
        
        # Token age risk
        if age_hours < 6:
            risk_factors.append(("very_new", 25))
        elif age_hours < 24:
            risk_factors.append(("new", 15))
        elif age_hours < 168:
            risk_factors.append(("recent", 5))
        
        # Source reliability
        if any(s in source for s in ["twitter", "telegram", "reddit"]):
            risk_factors.append(("social_source", 15))
        elif any(s in source for s in ["cg_trend", "cmc_trend"]):
            risk_factors.append(("established_source", 0))
        else:
            risk_factors.append(("dex_source", 10))
        
        # Signal strength
        if score > 500:
            confidence_factors.append(("very_strong_signal", 25))
        elif score > 300:
            confidence_factors.append(("strong_signal", 15))
        elif score > 150:
            confidence_factors.append(("moderate_signal", 5))
        
        total_risk = sum(f[1] for f in risk_factors)
        total_confidence = sum(f[1] for f in confidence_factors)
        risk_score = min(total_risk, 100)
        
        risk_multiplier = (100 - risk_score) / 100
        confidence_multiplier = 1 + (total_confidence / 100)
        
        base_position = settings.total_portfolio_usd / settings.max_open_positions
        calculated_position = base_position * risk_multiplier * confidence_multiplier
        position_size = max(settings.min_position_usd, min(calculated_position, settings.max_position_usd))
        
        return {
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "confidence_factors": confidence_factors,
            "recommended_position_usd": round(position_size, 2),
            "risk_level": "HIGH" if risk_score > 60 else "MEDIUM" if risk_score > 30 else "LOW"
        }
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        """
        AI decision on whether to sell based on momentum analysis
        """
        coin = position["coin"]
        buy_price = position["buy_price"]
        
        decision = {
            "should_sell": False,
            "reason": "",
            "predicted_upside": 0,
            "confidence": 0
        }
        
        # Always respect hard stop loss
        if pnl_percent <= -settings.stop_loss_percent:
            decision["should_sell"] = True
            decision["reason"] = f"Stop loss hit ({pnl_percent:.1f}%)"
            decision["confidence"] = 100
            return decision
        
        # Always take profit at target
        if pnl_percent >= settings.take_profit_percent:
            decision["should_sell"] = True
            decision["reason"] = f"Take profit target reached ({pnl_percent:.1f}%)"
            decision["confidence"] = 100
            return decision
        
        # Get momentum analysis
        momentum = await self.get_token_momentum(coin)
        
        # === Smart Exit Logic ===
        
        # In profit and momentum dying
        if pnl_percent > 5:
            if momentum["trend"] == "down" and momentum["confidence"] > 50:
                decision["should_sell"] = True
                decision["reason"] = f"In profit +{pnl_percent:.1f}%, momentum turning down"
                decision["confidence"] = momentum["confidence"]
                return decision
            
            if momentum["volume_trend"] == "declining" and momentum["predicted_upside"] < 5:
                decision["should_sell"] = True
                decision["reason"] = f"In profit +{pnl_percent:.1f}%, volume dying"
                decision["confidence"] = momentum["confidence"]
                return decision
        
        # Small profit but no more upside expected
        if pnl_percent > 3 and momentum["predicted_upside"] < 3 and momentum["confidence"] > 60:
            decision["should_sell"] = True
            decision["reason"] = f"Locked in +{pnl_percent:.1f}%, limited upside ({momentum['predicted_upside']:.1f}%)"
            decision["confidence"] = momentum["confidence"]
            return decision
        
        # Peaked and reversing hard
        if pnl_percent > 0 and momentum["strength"] < -5 and momentum["confidence"] > 50:
            decision["should_sell"] = True
            decision["reason"] = f"Price reversing, locking in +{pnl_percent:.1f}%"
            decision["confidence"] = momentum["confidence"]
            return decision
        
        # Hold if upside potential exists
        if momentum["predicted_upside"] > 10 and momentum["trend"] == "up":
            decision["should_sell"] = False
            decision["reason"] = f"Strong upside potential ({momentum['predicted_upside']:.1f}%), holding"
            decision["predicted_upside"] = momentum["predicted_upside"]
            decision["confidence"] = momentum["confidence"]
        
        return decision
    
    async def process_signals(self, signals: list[dict]):
        if not settings.trading_enabled:
            print("⏸️ Trading disabled")
            return
        
        open_positions = await self.db.get_open_positions()
        if len(open_positions) >= settings.max_open_positions:
            print(f"📊 Max positions reached ({len(open_positions)}/{settings.max_open_positions})")
            return
        
        used_capital = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in open_positions)
        available_capital = settings.total_portfolio_usd - used_capital
        
        for signal in signals[:5]:
            coin = signal["coin"]
            
            if await self.db.has_open_position(coin):
                continue
            
            price = await self.get_current_price(coin)
            if price == 0:
                continue
            
            market_cap = signal.get("market_cap", 0)
            if market_cap == 0:
                market_cap = await self.get_market_cap(coin)
            
            if settings.use_ai_sizing:
                risk_analysis = self.calculate_risk_score(signal, market_cap)
                position_usd = min(risk_analysis["recommended_position_usd"], available_capital)
                
                print(f"🤖 AI ANALYSIS {coin}: {risk_analysis['risk_level']} risk ({risk_analysis['risk_score']}/100)")
                print(f"   Recommended: ${position_usd:.2f}")
            else:
                position_usd = min(settings.max_position_usd, available_capital)
                risk_analysis = {"risk_score": 50}
            
            if position_usd < settings.min_position_usd:
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
                    "risk_score": risk_analysis["risk_score"],
                    "signal": signal
                })
                available_capital -= position_usd
            break
    
    async def buy(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER BUY: {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        
        if not self.exchange:
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
            return True
        
        try:
            order = self.exchange.create_market_sell_order(f"{coin}/USD", quantity)
            print(f"🔥 LIVE SELL: {order}")
            return True
        except Exception as e:
            print(f"❌ Sell failed: {e}")
            return False
    
    async def check_exit_conditions(self):
        """Smart exit with AI momentum analysis"""
        positions = await self.db.get_open_positions()
        
        for position in positions:
            coin = position["coin"]
            buy_price = position["buy_price"]
            quantity = position["quantity"]
            
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            # Get smart sell decision
            sell_decision = await self.should_smart_sell(position, current_price, pnl_percent)
            
            if sell_decision["should_sell"]:
                emoji = "🎯" if pnl_percent > 0 else "🛑"
                print(f"{emoji} SMART SELL: {coin} @ {pnl_percent:+.1f}%")
                print(f"   Reason: {sell_decision['reason']}")
                print(f"   Confidence: {sell_decision['confidence']}%")
                
                success = await self.sell(coin, quantity, current_price)
                if success:
                    await self.db.close_position(coin, current_price)
            else:
                upside = sell_decision.get('predicted_upside', 0)
                print(f"📊 Holding {coin}: {pnl_percent:+.1f}% (predicted upside: {upside:+.1f}%)")
