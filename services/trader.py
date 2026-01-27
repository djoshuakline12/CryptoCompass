import aiohttp
import os
from datetime import datetime, timezone
from config import settings
from database import Database
from services.dex_trader import dex_trader

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.token_data_cache = {}
        self.position_highs = {}
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_token_data(self, coin: str) -> dict:
        coin = coin.upper().strip()
        
        if coin in self.token_data_cache:
            cached = self.token_data_cache[coin]
            if (datetime.now(timezone.utc) - cached["timestamp"]).seconds < 120:
                return cached["data"]
        
        session = await self.get_session()
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        
        data = {
            "price": 0, "market_cap": 0, "liquidity": 0, "volume_24h": 0,
            "change_24h": 0, "change_1h": 0, "change_5m": 0,
            "buys_1h": 0, "sells_1h": 0, "source": "unknown",
            "contract_address": None, "chain": None
        }
        
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    pairs = result.get("pairs", [])
                    
                    best_pair = None
                    best_liquidity = 0
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper().strip()
                        chain = pair.get("chainId", "")
                        
                        if symbol == coin and chain == target_chain:
                            liq = float(pair.get("liquidity", {}).get("usd") or 0)
                            if liq > best_liquidity:
                                best_liquidity = liq
                                best_pair = pair
                    
                    if not best_pair:
                        for pair in pairs:
                            symbol = pair.get("baseToken", {}).get("symbol", "").upper().strip()
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
                        data["change_24h"] = float(best_pair.get("priceChange", {}).get("h24") or 0)
                        data["change_1h"] = float(best_pair.get("priceChange", {}).get("h1") or 0)
                        data["change_5m"] = float(best_pair.get("priceChange", {}).get("m5") or 0)
                        txns = best_pair.get("txns", {})
                        data["buys_1h"] = txns.get("h1", {}).get("buys", 0)
                        data["sells_1h"] = txns.get("h1", {}).get("sells", 0)
                        data["source"] = "dexscreener"
                        data["contract_address"] = best_pair.get("baseToken", {}).get("address")
                        data["chain"] = best_pair.get("chainId")
        except Exception as e:
            print(f"Token data error for {coin}: {e}")
        
        self.token_data_cache[coin] = {"data": data, "timestamp": datetime.now(timezone.utc)}
        return data
    
    async def get_current_price(self, coin: str) -> float:
        data = await self.get_token_data(coin)
        return data["price"]
    
    async def is_good_buy(self, coin: str, signal: dict) -> tuple:
        data = await self.get_token_data(coin)
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        
        if data["price"] == 0:
            return False, "No price data"
        
        if data["chain"] != target_chain:
            return False, f"Wrong chain ({data['chain']}, need {target_chain})"
        
        if data["market_cap"] < settings.min_market_cap:
            return False, f"MC too low ${data['market_cap']:,.0f}"
        if data["market_cap"] > settings.max_market_cap:
            return False, f"MC too high ${data['market_cap']:,.0f}"
        if data["liquidity"] < settings.min_liquidity:
            return False, f"Low liquidity ${data['liquidity']:,.0f}"
        if data["volume_24h"] < settings.min_volume_24h:
            return False, f"Low volume ${data['volume_24h']:,.0f}"
        if data["buys_1h"] + data["sells_1h"] < 3:
            return False, "No trading activity"
        if data["change_1h"] < -10:
            return False, f"Dumping {data['change_1h']:.0f}%"
        
        return True, "Passed"
    
    def calculate_position_size(self, available_usdc: float, risk_score: int) -> float:
        """
        Dynamic position sizing based on available funds.
        - Uses 20-50% of available balance per trade
        - Lower risk = bigger position
        - Minimum $1 trade, maximum 50% of balance
        """
        # Base: 30% of available
        base_percent = 0.30
        
        # Adjust by risk (lower risk = higher percent)
        risk_adjustment = (100 - risk_score) / 100  # 0.1 to 0.9
        position_percent = base_percent * (0.5 + risk_adjustment)  # 15% to 45%
        
        # Calculate position
        position_usd = available_usdc * position_percent
        
        # Enforce limits
        min_trade = max(1.0, available_usdc * 0.10)  # At least $1 or 10% of balance
        max_trade = available_usdc * 0.50  # Never more than 50%
        
        position_usd = max(min_trade, min(max_trade, position_usd))
        
        # Absolute minimum to avoid dust trades
        if position_usd < 0.50:
            return 0
        
        return round(position_usd, 2)
    
    def calculate_risk_score(self, signal: dict, data: dict) -> int:
        """Calculate risk score 0-100 (higher = riskier)"""
        risk = 50
        
        if data["liquidity"] > 100000:
            risk -= 15
        elif data["liquidity"] > 50000:
            risk -= 10
        elif data["liquidity"] < 20000:
            risk += 15
        
        if data["volume_24h"] > data["liquidity"] * 2:
            risk -= 10
        
        if data["change_1h"] > 20:
            risk += 10
        if data["change_1h"] < -5:
            risk += 10
        
        buy_ratio = data["buys_1h"] / max(data["buys_1h"] + data["sells_1h"], 1)
        if buy_ratio > 0.6:
            risk -= 10
        elif buy_ratio < 0.4:
            risk += 10
        
        return max(10, min(90, risk))
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        """AI-enhanced sell decision with trailing stops."""
        coin = position["coin"]
        data = await self.get_token_data(coin)
        
        # Track position high for trailing stop
        if coin not in self.position_highs:
            self.position_highs[coin] = pnl_percent
        else:
            self.position_highs[coin] = max(self.position_highs[coin], pnl_percent)
        
        peak = self.position_highs[coin]
        drawdown = peak - pnl_percent
        
        # EMERGENCY EXITS
        if data["liquidity"] < 5000:
            return {"should_sell": True, "reason": "⚠️ Liquidity crisis"}
        
        if pnl_percent <= -20:
            return {"should_sell": True, "reason": f"Hard stop {pnl_percent:.1f}%"}
        
        # TRAILING STOPS - protect gains
        if peak >= 100 and drawdown > 30:
            return {"should_sell": True, "reason": f"Trailing stop: was +{peak:.0f}%, now +{pnl_percent:.0f}%"}
        if peak >= 50 and drawdown > 25:
            return {"should_sell": True, "reason": f"Trailing stop: was +{peak:.0f}%, now +{pnl_percent:.0f}%"}
        if peak >= 25 and drawdown > 15:
            return {"should_sell": True, "reason": f"Trailing stop: was +{peak:.0f}%, now +{pnl_percent:.0f}%"}
        
        # MOMENTUM CHECKS
        volume_healthy = data["volume_24h"] > 10000
        momentum_positive = data["change_1h"] > -5 and data["change_5m"] > -10
        activity = data["buys_1h"] + data["sells_1h"]
        buy_pressure = data["buys_1h"] / max(activity, 1)
        
        # AI DECISION
        if os.getenv("ANTHROPIC_API_KEY") and settings.use_ai_smart_sell:
            try:
                import anthropic
                client = anthropic.Anthropic()
                
                prompt = f"""Meme coin trading decision. Be concise.

POSITION: {coin}
- P&L: {pnl_percent:+.1f}% (peak was +{peak:.1f}%)
- Price: ${current_price:.8f}

METRICS:
- Liquidity: ${data['liquidity']:,.0f}
- 24h Volume: ${data['volume_24h']:,.0f}
- 1h change: {data['change_1h']:+.1f}%
- 5m change: {data['change_5m']:+.1f}%
- Buys/Sells 1h: {data['buys_1h']}/{data['sells_1h']}

RULES:
- Profitable + strong momentum → HOLD
- Profitable + weak momentum → SELL
- Losing + recovering momentum → HOLD
- Losing + dead momentum → SELL
- Meme coins can 100x - don't sell winners early!

Reply: SELL or HOLD, then 5-word reason.
"""
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=50,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                answer = response.content[0].text.strip().upper()
                reason = response.content[0].text.strip()
                
                print(f"   🤖 AI: {reason}")
                
                if answer.startswith("SELL"):
                    return {"should_sell": True, "reason": f"AI: {reason}"}
                else:
                    return {"should_sell": False, "reason": ""}
                    
            except Exception as e:
                print(f"   AI error: {e}")
        
        # FALLBACK RULES
        if pnl_percent > 10 and not momentum_positive:
            return {"should_sell": True, "reason": "Momentum fading"}
        
        if pnl_percent < -10 and not volume_healthy:
            return {"should_sell": True, "reason": "Low volume, cutting losses"}
        
        if pnl_percent < -5 and buy_pressure < 0.3:
            return {"should_sell": True, "reason": "Heavy selling pressure"}
        
        return {"should_sell": False, "reason": ""}
    
    async def process_signals(self, signals: list):
        if not settings.trading_enabled:
            return
        if settings.is_daily_loss_limit_hit():
            return
        
        positions = await self.db.get_open_positions()
        if len(positions) >= settings.max_open_positions:
            return
        
        # Get ACTUAL available USDC from wallet
        available_usdc = 0
        if dex_trader.initialized:
            balances = await dex_trader.get_balances()
            available_usdc = balances.get("usdc", 0)
            print(f"💰 Available USDC: ${available_usdc:.2f}")
        
        if available_usdc < 0.50:
            print(f"⚠️ Insufficient USDC (${available_usdc:.2f}) - skipping buys")
            return
        
        for signal in signals[:15]:
            coin = signal["coin"].upper().strip()
            
            if settings.is_coin_blacklisted(coin):
                continue
            if settings.is_coin_on_cooldown(coin):
                continue
            if await self.db.has_open_position(coin):
                continue
            
            is_good, reason = await self.is_good_buy(coin, signal)
            if not is_good:
                print(f"⛔ Skip {coin}: {reason}")
                continue
            
            data = await self.get_token_data(coin)
            price = data["price"]
            contract = data["contract_address"]
            
            # Dynamic position sizing based on available funds
            risk_score = self.calculate_risk_score(signal, data)
            position_usd = self.calculate_position_size(available_usdc, risk_score)
            
            if position_usd < 0.50:
                print(f"⛔ Skip {coin}: Position too small (${position_usd:.2f})")
                continue
            
            print(f"📊 {coin}: Risk {risk_score}/100, Position ${position_usd:.2f} ({position_usd/available_usdc*100:.0f}% of balance)")
            
            if settings.live_trading and dex_trader.initialized:
                print(f"🔄 LIVE BUY: ${position_usd:.2f} of {coin} on {data['chain']}")
                result = await dex_trader.swap_usdc_to_token(contract, position_usd)
                
                if not result["success"]:
                    print(f"❌ Swap failed: {result['error']}")
                    continue
                
                print(f"✅ Swap success!")
            else:
                print(f"📝 PAPER BUY: {coin} @ ${price:.8f}")
            
            quantity = position_usd / price
            
            await self.db.open_position({
                "coin": coin,
                "quantity": quantity,
                "buy_price": price,
                "position_usd": position_usd,
                "market_cap": data["market_cap"],
                "risk_score": risk_score,
                "contract_address": contract,
                "chain": data["chain"],
                "signal": signal
            })
            
            print(f"✅ Opened: {coin} ${position_usd:.2f} on {data['chain']}")
            break
        
        settings.record_successful_scan()
    
    async def check_exit_conditions(self):
        positions = await self.db.get_open_positions()
        
        for pos in positions:
            coin = pos["coin"]
            buy_price = pos["buy_price"]
            contract = pos.get("contract_address")
            
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            decision = await self.should_smart_sell(pos, current_price, pnl_percent)
            
            if decision["should_sell"]:
                if settings.live_trading and dex_trader.initialized and contract:
                    print(f"🔄 LIVE SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                    result = await dex_trader.swap_token_to_usdc(contract)
                    
                    if not result["success"]:
                        print(f"❌ Sell failed: {result['error']}")
                        continue
                    
                    print(f"✅ Sell success!")
                else:
                    print(f"📝 PAPER SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                
                if coin in self.position_highs:
                    del self.position_highs[coin]
                
                await self.db.close_position(coin, current_price, decision["reason"])
                if pnl_percent < 0:
                    settings.add_coin_cooldown(coin)

    async def get_live_price(self, coin: str) -> dict:
        """Get fresh price data, bypassing cache"""
        session = await self.get_session()
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        
        data = {
            "price": 0, "liquidity": 0, "volume_24h": 0,
            "change_1h": 0, "change_5m": 0, "buys_1h": 0, "sells_1h": 0
        }
        
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    pairs = result.get("pairs", [])
                    
                    for pair in pairs:
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper().strip()
                        chain = pair.get("chainId", "")
                        
                        if symbol == coin.upper() and chain == target_chain:
                            data["price"] = float(pair.get("priceUsd") or 0)
                            data["liquidity"] = float(pair.get("liquidity", {}).get("usd") or 0)
                            data["volume_24h"] = float(pair.get("volume", {}).get("h24") or 0)
                            data["change_1h"] = float(pair.get("priceChange", {}).get("h1") or 0)
                            data["change_5m"] = float(pair.get("priceChange", {}).get("m5") or 0)
                            txns = pair.get("txns", {})
                            data["buys_1h"] = txns.get("h1", {}).get("buys", 0)
                            data["sells_1h"] = txns.get("h1", {}).get("sells", 0)
                            break
        except Exception as e:
            print(f"Live price error for {coin}: {e}")
        
        return data
    
    async def check_exit_conditions_live(self):
        """Check positions with live prices (no cache)"""
        positions = await self.db.get_open_positions()
        
        if not positions:
            return
        
        for pos in positions:
            coin = pos["coin"]
            buy_price = pos["buy_price"]
            contract = pos.get("contract_address")
            
            # Get LIVE price, bypass cache
            data = await self.get_live_price(coin)
            current_price = data["price"]
            
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            # Update cache with live data for the sell decision
            self.token_data_cache[coin.upper()] = {
                "data": {**data, "contract_address": contract, "chain": dex_trader.chain},
                "timestamp": datetime.now(timezone.utc)
            }
            
            decision = await self.should_smart_sell(pos, current_price, pnl_percent)
            
            if decision["should_sell"]:
                if settings.live_trading and dex_trader.initialized and contract:
                    print(f"🔄 LIVE SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                    result = await dex_trader.swap_token_to_usdc(contract)
                    
                    if not result["success"]:
                        print(f"❌ Sell failed: {result['error']}")
                        continue
                    
                    print(f"✅ Sell success!")
                else:
                    print(f"📝 PAPER SELL: {coin} @ {pnl_percent:+.1f}% - {decision['reason']}")
                
                if coin in self.position_highs:
                    del self.position_highs[coin]
                
                await self.db.close_position(coin, current_price, decision["reason"])
                if pnl_percent < 0:
                    settings.add_coin_cooldown(coin)
