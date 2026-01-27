import aiohttp
from datetime import datetime, timezone
from config import settings
from database import Database
from services.dex_trader import dex_trader

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.token_data_cache = {}
    
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
                    
                    # First try to find pair on target chain
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
                    
                    # If no pair on target chain, find best pair on any chain (for display)
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
            return False, f"Wrong chain ({data['chain'] or 'unknown'}, need {target_chain})"
        
        if data["contract_address"] is None:
            return False, "No contract address"
        if data["liquidity"] < settings.min_liquidity:
            return False, f"Low liquidity ${data['liquidity']:,.0f}"
        if data["volume_24h"] < settings.min_volume_24h:
            return False, f"Low volume ${data['volume_24h']:,.0f}"
        if data["market_cap"] > 0:
            if data["market_cap"] > settings.max_market_cap:
                return False, f"MC too high ${data['market_cap']:,.0f}"
            if data["market_cap"] < settings.min_market_cap:
                return False, f"MC too low ${data['market_cap']:,.0f}"
        if data["buys_1h"] + data["sells_1h"] < 3:
            return False, "No trading activity"
        if data["change_1h"] < -15:
            return False, f"Dumping {data['change_1h']:.0f}%"
        
        return True, "OK"
    
    def calculate_risk_score(self, signal: dict, token_data: dict) -> dict:
        risk = 0
        mc = token_data["market_cap"]
        liq = token_data["liquidity"]
        vol = token_data["volume_24h"]
        
        if mc == 0: risk += 25
        elif mc < 10_000_000: risk += 20
        elif mc < 50_000_000: risk += 10
        
        if liq < 50_000: risk += 25
        elif liq < 100_000: risk += 15
        
        if vol < 50_000: risk += 20
        elif vol < 100_000: risk += 10
        
        source = signal.get("source", "")
        if any(s in source for s in ["twitter", "telegram", "reddit"]): risk += 15
        
        risk = min(risk, 100)
        multiplier = (100 - risk) / 100
        base = settings.total_portfolio_usd / settings.max_open_positions
        size = max(settings.min_position_usd, min(base * multiplier, settings.max_position_usd))
        
        return {
            "risk_score": risk,
            "recommended_position_usd": round(size, 2),
            "risk_level": "HIGH" if risk > 60 else "MEDIUM" if risk > 30 else "LOW"
        }
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        if pnl_percent <= -settings.stop_loss_percent:
            return {"should_sell": True, "reason": f"Stop loss {pnl_percent:.1f}%"}
        if pnl_percent >= settings.take_profit_percent:
            return {"should_sell": True, "reason": f"Take profit {pnl_percent:.1f}%"}
        
        data = await self.get_token_data(position["coin"])
        
        if pnl_percent > 5 and data["change_1h"] < -5:
            return {"should_sell": True, "reason": "Momentum slowing"}
        if data["buys_1h"] + data["sells_1h"] < 3:
            if pnl_percent > 0:
                return {"should_sell": True, "reason": "Low activity, taking profit"}
            elif pnl_percent < -3:
                return {"should_sell": True, "reason": "Low activity, cutting losses"}
        
        return {"should_sell": False, "reason": ""}
    
    async def process_signals(self, signals: list):
        if not settings.trading_enabled:
            return
        if settings.is_daily_loss_limit_hit():
            return
        
        positions = await self.db.get_open_positions()
        if len(positions) >= settings.max_open_positions:
            return
        
        used = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in positions)
        available = settings.total_portfolio_usd - used
        
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
            
            risk = self.calculate_risk_score(signal, data)
            position_usd = min(risk["recommended_position_usd"], available)
            
            if position_usd < settings.min_position_usd:
                print(f"⛔ Skip {coin}: Position too small ${position_usd:.2f}")
                continue
            
            # Execute real swap if live trading enabled
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
                "risk_score": risk["risk_score"],
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
                    print(f"🔄 LIVE SELL: {coin} @ {pnl_percent:+.1f}%")
                    result = await dex_trader.swap_token_to_usdc(contract)
                    
                    if not result["success"]:
                        print(f"❌ Sell failed: {result['error']}")
                        continue
                    
                    print(f"✅ Sell success!")
                else:
                    print(f"📝 PAPER SELL: {coin} @ {pnl_percent:+.1f}%")
                
                await self.db.close_position(coin, current_price, decision["reason"])
                if pnl_percent < 0:
                    settings.add_coin_cooldown(coin)

# Import at top of file - adding to existing trader
