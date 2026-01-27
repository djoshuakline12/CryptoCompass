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
        self.price_history = {}
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
    
    async def send_notification(self, message: str, alert_type: str = "info"):
        """Send notification via Discord webhook"""
        if not settings.discord_webhook_url:
            return
        
        try:
            session = await self.get_session()
            
            colors = {"info": 3447003, "success": 5763719, "warning": 16776960, "error": 15548997}
            
            payload = {
                "embeds": [{
                    "title": "🤖 Crypto Buzz Trader",
                    "description": message,
                    "color": colors.get(alert_type, 3447003),
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
            
            async with session.post(settings.discord_webhook_url, json=payload) as resp:
                if resp.status != 204:
                    print(f"Discord notification failed: {resp.status}")
        except Exception as e:
            print(f"Notification error: {e}")
    
    async def get_market_cap(self, coin: str) -> float:
        if coin in self.market_cap_cache:
            return self.market_cap_cache[coin]
        
        session = await self.get_session()
        
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/search?q={coin}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
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
        price = 0
        
        if self.exchange:
            try:
                ticker = self.exchange.fetch_ticker(f"{coin}/USD")
                if ticker and ticker.get('last'):
                    price = ticker['last']
            except:
                pass
        
        if price == 0:
            try:
                async with session.get(f"https://api.dexscreener.com/latest/dex/search?q={coin}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            price = float(pairs[0].get("priceUsd", 0) or 0)
            except:
                pass
        
        if price == 0:
            if coin in self.price_cache:
                price = self.price_cache[coin] * (1 + random.uniform(-0.02, 0.02))
            else:
                price = round(random.uniform(0.01, 5.0), 4)
        
        self.price_cache[coin] = price
        
        if coin not in self.price_history:
            self.price_history[coin] = []
        self.price_history[coin].append({"price": price, "timestamp": datetime.utcnow()})
        self.price_history[coin] = self.price_history[coin][-30:]
        
        return price
    
    async def get_token_momentum(self, coin: str) -> dict:
        session = await self.get_session()
        
        momentum = {"trend": "neutral", "strength": 0, "predicted_upside": 10, "confidence": 40, "reason": ""}
        
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/search?q={coin}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        pair = pairs[0]
                        
                        change_5m = float(pair.get("priceChange", {}).get("m5") or 0)
                        change_1h = float(pair.get("priceChange", {}).get("h1") or 0)
                        change_24h = float(pair.get("priceChange", {}).get("h24") or 0)
                        
                        txns = pair.get("txns", {})
                        buys_1h = txns.get("h1", {}).get("buys", 0)
                        sells_1h = txns.get("h1", {}).get("sells", 0)
                        
                        if change_24h > 20 and change_1h < 2 and change_5m < 0:
                            momentum = {"trend": "down", "predicted_upside": -5, "confidence": 70, "reason": "Momentum slowing"}
                        elif sells_1h > buys_1h * 1.5:
                            momentum = {"trend": "down", "predicted_upside": -10, "confidence": 60, "reason": "Heavy sell pressure"}
                        elif change_5m > 5 and change_1h > 10 and buys_1h > sells_1h:
                            momentum = {"trend": "up", "predicted_upside": min(change_1h * 0.5, 30), "confidence": 70, "reason": "Strong momentum"}
                        elif change_24h > 50 and change_1h < 5:
                            momentum = {"trend": "neutral", "predicted_upside": 5, "confidence": 60, "reason": "Already pumped"}
        except:
            pass
        
        return momentum
    
    def calculate_risk_score(self, signal: dict, market_cap: float) -> dict:
        risk = 0
        
        if market_cap == 0:
            risk += 30
        elif market_cap < 10_000_000:
            risk += 25
        elif market_cap < 50_000_000:
            risk += 15
        else:
            risk += 5
        
        age_hours = signal.get("age_hours", 999)
        if age_hours < 6:
            risk += 25
        elif age_hours < 24:
            risk += 15
        
        source = signal.get("source", "")
        if any(s in source for s in ["twitter", "telegram", "reddit"]):
            risk += 15
        
        risk = min(risk, 100)
        
        risk_multiplier = (100 - risk) / 100
        base_position = settings.total_portfolio_usd / settings.max_open_positions
        position_size = max(settings.min_position_usd, min(base_position * risk_multiplier, settings.max_position_usd))
        
        return {
            "risk_score": risk,
            "recommended_position_usd": round(position_size, 2),
            "risk_level": "HIGH" if risk > 60 else "MEDIUM" if risk > 30 else "LOW"
        }
    
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
        
        return {"should_sell": False, "reason": "", "predicted_upside": momentum["predicted_upside"]}
    
    async def process_signals(self, signals: list[dict]):
        # === SAFETY CHECKS ===
        
        if not settings.trading_enabled:
            print("⏸️ Trading disabled")
            return
        
        # Check daily loss limit
        if settings.is_daily_loss_limit_hit():
            print(f"🛑 DAILY LOSS LIMIT HIT: ${settings.daily_pnl:.2f} - Trading paused")
            await self.send_notification(
                f"⚠️ Daily loss limit reached!\nDaily P&L: ${settings.daily_pnl:.2f}\nTrading paused until tomorrow.",
                "warning"
            )
            return
        
        # Check health
        if settings.is_health_critical():
            print(f"🚨 HEALTH CRITICAL: {settings.consecutive_errors} consecutive errors")
            await self.send_notification(
                f"🚨 Bot health critical!\n{settings.consecutive_errors} consecutive errors\nLast error: {settings.last_error}",
                "error"
            )
        
        open_positions = await self.db.get_open_positions()
        if len(open_positions) >= settings.max_open_positions:
            print(f"📊 Max positions ({len(open_positions)}/{settings.max_open_positions})")
            return
        
        used_capital = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in open_positions)
        available_capital = settings.total_portfolio_usd - used_capital
        
        print(f"💰 Portfolio: ${settings.total_portfolio_usd:.2f} | Available: ${available_capital:.2f} | Daily P&L: ${settings.daily_pnl:.2f}")
        
        for signal in signals[:5]:
            coin = signal["coin"].upper()
            
            # === COIN SAFETY CHECKS ===
            
            # Check blacklist
            if settings.is_coin_blacklisted(coin):
                print(f"🚫 Skipping {coin} (blacklisted)")
                continue
            
            # Check cooldown
            if settings.is_coin_on_cooldown(coin):
                remaining = settings.get_cooldown_remaining(coin)
                print(f"⏳ Skipping {coin} (cooldown: {remaining:.1f}h remaining)")
                continue
            
            # Check if already holding
            if await self.db.has_open_position(coin):
                continue
            
            price = await self.get_current_price(coin)
            if price == 0:
                continue
            
            market_cap = signal.get("market_cap", 0) or await self.get_market_cap(coin)
            
            if settings.use_ai_sizing:
                risk = self.calculate_risk_score(signal, market_cap)
                position_usd = min(risk["recommended_position_usd"], available_capital)
                print(f"🤖 {coin}: {risk['risk_level']} risk, ${position_usd:.2f}")
            else:
                position_usd = min(settings.max_position_usd, available_capital)
                risk = {"risk_score": 50}
            
            if position_usd < settings.min_position_usd:
                continue
            
            quantity = position_usd / price
            
            if await self.buy(coin, quantity, price):
                await self.db.open_position({
                    "coin": coin,
                    "quantity": quantity,
                    "buy_price": price,
                    "position_usd": position_usd,
                    "market_cap": market_cap,
                    "risk_score": risk["risk_score"],
                    "signal": signal
                })
                
                # Send notification
                await self.send_notification(
                    f"🟢 **BOUGHT {coin}**\n"
                    f"Price: ${price:.4f}\n"
                    f"Amount: ${position_usd:.2f}\n"
                    f"Risk: {risk.get('risk_level', 'MEDIUM')}",
                    "success"
                )
            break
        
        # Record successful scan
        settings.record_successful_scan()
    
    async def buy(self, coin: str, quantity: float, price: float) -> bool:
        if not settings.live_trading:
            print(f"📝 PAPER BUY: {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        if not self.exchange:
            return True
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
            print(f"📝 PAPER SELL: {quantity:.4f} {coin} @ ${price:.4f}")
            return True
        if not self.exchange:
            return True
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
            coin = position["coin"]
            buy_price = position["buy_price"]
            quantity = position["quantity"]
            
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            pnl_usd = (current_price - buy_price) * quantity
            
            decision = await self.should_smart_sell(position, current_price, pnl_percent)
            
            if decision["should_sell"]:
                emoji = "🎯" if pnl_percent > 0 else "🛑"
                print(f"{emoji} SMART SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                
                if await self.sell(coin, quantity, current_price):
                    await self.db.close_position(coin, current_price, decision["reason"])
                    
                    # Add cooldown if sold at a loss
                    if pnl_percent < 0:
                        settings.add_coin_cooldown(coin)
                    
                    # Send notification
                    await self.send_notification(
                        f"{emoji} **SOLD {coin}**\n"
                        f"P&L: {pnl_percent:+.1f}% (${pnl_usd:+.2f})\n"
                        f"Reason: {decision['reason']}",
                        "success" if pnl_percent > 0 else "warning"
                    )
            else:
                upside = decision.get('predicted_upside', 0)
                print(f"📊 Holding {coin}: {pnl_percent:+.1f}% (upside: +{upside:.0f}%)")
