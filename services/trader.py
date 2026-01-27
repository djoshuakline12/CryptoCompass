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
        self.market_cap_cache = {}
        self.price_history = {}
        self.token_data_cache = {}
        self.exchange = self._init_exchange()
    
    def _init_exchange(self):
        if not settings.exchange_api_key:
            print("⚠️  Exchange not configured - paper trading only")
            return None
        try:
            import ccxt
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
    
    async def send_notification(self, message: str, alert_type: str = "info"):
        if not settings.discord_webhook_url:
            return
        try:
            session = await self.get_session()
            colors = {"info": 3447003, "success": 5763719, "warning": 16776960, "error": 15548997}
            payload = {"embeds": [{"title": "🤖 Crypto Buzz Trader", "description": message, "color": colors.get(alert_type, 3447003)}]}
            await session.post(settings.discord_webhook_url, json=payload)
        except:
            pass
    
    async def get_token_data(self, coin: str) -> dict:
        coin = coin.upper()
        
        if coin in self.token_data_cache:
            cached = self.token_data_cache[coin]
            if (datetime.utcnow() - cached["timestamp"]).seconds < 120:
                return cached["data"]
        
        session = await self.get_session()
        
        data = {
            "price": 0, "market_cap": 0, "liquidity": 0, "volume_24h": 0,
            "volume_1h": 0, "change_24h": 0, "change_1h": 0, "change_5m": 0,
            "buys_1h": 0, "sells_1h": 0, "is_tradeable": False, "source": "unknown"
        }
        
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    pairs = result.get("pairs", [])
                    
                    best_pair = None
                    best_liquidity = 0
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        if symbol == coin:
                            liq = float(pair.get("liquidity", {}).get("usd") or 0)
                            if liq > best_liquidity:
                                best_liquidity = liq
                                best_pair = pair
                    
                    if best_pair:
                        data["price"] = float(best_pair.get("priceUsd") or 0)
                        data["market_cap"] = float(best_pair.get("fdv") or 0)
                        data["liquidity"] = float(best_pair.get("liquidity", {}).get("usd") or 0)
                        data["volume_24h"] = float(best_pair.get("volume", {}).get("h24") or 0)
                        data["volume_1h"] = float(best_pair.get("volume", {}).get("h1") or 0)
                        data["change_24h"] = float(best_pair.get("priceChange", {}).get("h24") or 0)
                        data["change_1h"] = float(best_pair.get("priceChange", {}).get("h1") or 0)
                        data["change_5m"] = float(best_pair.get("priceChange", {}).get("m5") or 0)
                        txns = best_pair.get("txns", {})
                        data["buys_1h"] = txns.get("h1", {}).get("buys", 0)
                        data["sells_1h"] = txns.get("h1", {}).get("sells", 0)
                        data["source"] = "dexscreener"
        except Exception as e:
            print(f"Error fetching token data for {coin}: {e}")
        
        data["is_tradeable"] = (
            data["price"] > 0 and
            data["liquidity"] >= settings.min_liquidity and
            data["volume_24h"] >= settings.min_volume_24h
        )
        
        self.token_data_cache[coin] = {"data": data, "timestamp": datetime.utcnow()}
        return data
    
    async def get_current_price(self, coin: str) -> float:
        data = await self.get_token_data(coin)
        if data["price"] > 0:
            return data["price"]
        if coin in self.price_cache:
            return self.price_cache[coin] * (1 + random.uniform(-0.02, 0.02))
        return 0
    
    async def get_market_cap(self, coin: str) -> float:
        data = await self.get_token_data(coin)
        return data["market_cap"]
    
    async def get_token_momentum(self, coin: str) -> dict:
        data = await self.get_token_data(coin)
        momentum = {"trend": "neutral", "predicted_upside": 10, "confidence": 40, "reason": ""}
        
        if data["source"] == "unknown":
            return momentum
        
        change_5m, change_1h, change_24h = data["change_5m"], data["change_1h"], data["change_24h"]
        buys_1h, sells_1h = data["buys_1h"], data["sells_1h"]
        
        if change_24h > 20 and change_1h < 2 and change_5m < 0:
            momentum = {"trend": "down", "predicted_upside": -5, "confidence": 70, "reason": "Momentum slowing"}
        elif sells_1h > buys_1h * 1.5:
            momentum = {"trend": "down", "predicted_upside": -10, "confidence": 60, "reason": "Heavy sell pressure"}
        elif change_5m > 5 and change_1h > 10 and buys_1h > sells_1h:
            momentum = {"trend": "up", "predicted_upside": min(change_1h * 0.5, 30), "confidence": 70, "reason": "Strong momentum"}
        elif change_24h > 50 and change_1h < 5:
            momentum = {"trend": "neutral", "predicted_upside": 5, "confidence": 60, "reason": "Already pumped"}
        
        return momentum
    
    def calculate_risk_score(self, signal: dict, token_data: dict) -> dict:
        risk = 0
        market_cap, liquidity, volume_24h = token_data["market_cap"], token_data["liquidity"], token_data["volume_24h"]
        
        if market_cap == 0: risk += 25
        elif market_cap < 10_000_000: risk += 20
        elif market_cap < 50_000_000: risk += 10
        elif market_cap > 200_000_000: risk += 5
        
        if liquidity < 50_000: risk += 25
        elif liquidity < 100_000: risk += 15
        
        if volume_24h < 50_000: risk += 20
        elif volume_24h < 100_000: risk += 10
        
        source = signal.get("source", "")
        if any(s in source for s in ["twitter", "telegram", "reddit"]): risk += 15
        
        age_hours = signal.get("age_hours", 999)
        if age_hours < 6: risk += 15
        elif age_hours < 24: risk += 10
        
        risk = min(risk, 100)
        risk_multiplier = (100 - risk) / 100
        base_position = settings.total_portfolio_usd / settings.max_open_positions
        position_size = max(settings.min_position_usd, min(base_position * risk_multiplier, settings.max_position_usd))
        
        return {
            "risk_score": risk,
            "recommended_position_usd": round(position_size, 2),
            "risk_level": "HIGH" if risk > 60 else "MEDIUM" if risk > 30 else "LOW"
        }
    
    async def is_good_buy(self, coin: str, signal: dict) -> tuple[bool, str]:
        token_data = await self.get_token_data(coin)
        
        if token_data["price"] == 0:
            return False, "No price data"
        if token_data["liquidity"] < settings.min_liquidity:
            return False, f"Low liquidity (${token_data['liquidity']:,.0f} < ${settings.min_liquidity:,.0f})"
        if token_data["volume_24h"] < settings.min_volume_24h:
            return False, f"Low volume (${token_data['volume_24h']:,.0f} < ${settings.min_volume_24h:,.0f})"
        if token_data["market_cap"] > 0:
            if token_data["market_cap"] > settings.max_market_cap:
                return False, f"Market cap too high (${token_data['market_cap']:,.0f})"
            if token_data["market_cap"] < settings.min_market_cap:
                return False, f"Market cap too low (${token_data['market_cap']:,.0f})"
        if token_data["buys_1h"] + token_data["sells_1h"] < 5:
            return False, "No recent trading activity"
        if token_data["change_1h"] < -10:
            return False, f"Dumping ({token_data['change_1h']:.1f}% in 1h)"
        
        return True, "Passed all filters"
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        coin = position["coin"]
        
        if pnl_percent <= -settings.stop_loss_percent:
            return {"should_sell": True, "reason": f"Stop loss ({pnl_percent:.1f}%)", "confidence": 100}
        if pnl_percent >= settings.take_profit_percent:
            return {"should_sell": True, "reason": f"Take profit ({pnl_percent:.1f}%)", "confidence": 100}
        
        momentum = await self.get_token_momentum(coin)
        
        if pnl_percent > 5 and momentum["trend"] == "down" and momentum["confidence"] > 50:
            return {"should_sell": True, "reason": f"+{pnl_percent:.1f}%, {momentum['reason']}", "confidence": momentum["confidence"]}
        if pnl_percent > 3 and momentum["predicted_upside"] < 3 and momentum["confidence"] > 50:
            return {"should_sell": True, "reason": f"Locked +{pnl_percent:.1f}%, limited upside", "confidence": momentum["confidence"]}
        
        token_data = await self.get_token_data(coin)
        if token_data["buys_1h"] + token_data["sells_1h"] < 3:
            if pnl_percent > 0:
                return {"should_sell": True, "reason": "Low activity, taking profit", "confidence": 60}
            elif pnl_percent < -3:
                return {"should_sell": True, "reason": "Low activity, cutting losses", "confidence": 50}
        
        return {"should_sell": False, "reason": "", "predicted_upside": momentum["predicted_upside"]}
    
    async def process_signals(self, signals: list[dict]):
        if not settings.trading_enabled:
            print("⏸️ Trading disabled")
            return
        if settings.is_daily_loss_limit_hit():
            print(f"🛑 DAILY LOSS LIMIT: ${settings.daily_pnl:.2f}")
            return
        
        open_positions = await self.db.get_open_positions()
        if len(open_positions) >= settings.max_open_positions:
            print(f"📊 Max positions ({len(open_positions)}/{settings.max_open_positions})")
            return
        
        used_capital = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in open_positions)
        available_capital = settings.total_portfolio_usd - used_capital
        print(f"💰 Portfolio: ${settings.total_portfolio_usd:.2f} | Available: ${available_capital:.2f}")
        
        bought = False
        for signal in signals[:10]:
            if bought: break
            coin = signal["coin"].upper()
            
            if settings.is_coin_blacklisted(coin): continue
            if settings.is_coin_on_cooldown(coin): continue
            if await self.db.has_open_position(coin): continue
            
            is_good, reason = await self.is_good_buy(coin, signal)
            if not is_good:
                print(f"⛔ Skipping {coin}: {reason}")
                continue
            
            token_data = await self.get_token_data(coin)
            price = token_data["price"]
            
            if settings.use_ai_sizing:
                risk = self.calculate_risk_score(signal, token_data)
                position_usd = min(risk["recommended_position_usd"], available_capital)
                print(f"🤖 {coin}: {risk['risk_level']} risk ({risk['risk_score']}/100)")
                print(f"   Liquidity: ${token_data['liquidity']:,.0f} | Volume: ${token_data['volume_24h']:,.0f}")
            else:
                position_usd = min(settings.max_position_usd, available_capital)
                risk = {"risk_score": 50}
            
            if position_usd < settings.min_position_usd: continue
            
            quantity = position_usd / price
            if await self.buy(coin, quantity, price):
                await self.db.open_position({
                    "coin": coin, "quantity": quantity, "buy_price": price,
                    "position_usd": position_usd, "market_cap": token_data["market_cap"],
                    "liquidity": token_data["liquidity"], "volume_24h": token_data["volume_24h"],
                    "risk_score": risk["risk_score"], "signal": signal
                })
                await self.send_notification(f"🟢 **BOUGHT {coin}**\nPrice: ${price:.6f}\nAmount: ${position_usd:.2f}", "success")
                bought = True
        
        settings.record_successful_scan()
    
    async def buy(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER BUY: {quantity:.4f} {coin} @ ${price:.6f}")
            return True
        if not self.exchange: return True
        try:
            self.exchange.create_market_buy_order(f"{coin}/USD", quantity)
            print(f"🔥 LIVE BUY: {coin}")
            return True
        except Exception as e:
            print(f"❌ Buy failed: {e}")
            settings.record_error(str(e))
            return False
    
    async def sell(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER SELL: {quantity:.4f} {coin} @ ${price:.6f}")
            return True
        if not self.exchange: return True
        try:
            self.exchange.create_market_sell_order(f"{coin}/USD", quantity)
            print(f"🔥 LIVE SELL: {coin}")
            return True
        except Exception as e:
            print(f"❌ Sell failed: {e}")
            settings.record_error(str(e))
            return False
    
    async def check_exit_conditions(self):
        positions = await self.db.get_open_positions()
        for position in positions:
            coin, buy_price, quantity = position["coin"], position["buy_price"], position["quantity"]
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                print(f"⚠️ Can't get price for {coin}")
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            pnl_usd = (current_price - buy_price) * quantity
            decision = await self.should_smart_sell(position, current_price, pnl_percent)
            
            if decision["should_sell"]:
                emoji = "🎯" if pnl_percent > 0 else "🛑"
                print(f"{emoji} SMART SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                if await self.sell(coin, quantity, current_price):
                    await self.db.close_position(coin, current_price, decision["reason"])
                    if pnl_percent < 0: settings.add_coin_cooldown(coin)
                    await self.send_notification(f"{emoji} **SOLD {coin}**\nP&L: {pnl_percent:+.1f}% (${pnl_usd:+.2f})\nReason: {decision['reason']}", "success" if pnl_percent > 0 else "warning")
            else:
                print(f"📊 Holding {coin}: {pnl_percent:+.1f}% (upside: +{decision.get('predicted_upside', 0):.0f}%)")
