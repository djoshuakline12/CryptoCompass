import aiohttp
import os
from datetime import datetime, timezone
from config import settings
from database import Database
from services.dex_trader import dex_trader
from services.token_safety import check_token_safety, get_token_age_hours

class Trader:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
        self.token_data_cache = {}
        self.position_highs = {}
        self.consecutive_wins = 0
        self.consecutive_losses = 0
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_token_data(self, coin: str) -> dict:
        coin = coin.upper().strip()
        
        if coin in self.token_data_cache:
            cached = self.token_data_cache[coin]
            if (datetime.now(timezone.utc) - cached["timestamp"]).seconds < 60:
                return cached["data"]
        
        session = await self.get_session()
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        
        data = {
            "price": 0, "market_cap": 0, "liquidity": 0, "volume_24h": 0,
            "change_24h": 0, "change_1h": 0, "change_5m": 0,
            "buys_1h": 0, "sells_1h": 0, "buys_5m": 0, "sells_5m": 0,
            "source": "unknown", "contract_address": None, "chain": None
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
                        data["buys_5m"] = txns.get("m5", {}).get("buys", 0)
                        data["sells_5m"] = txns.get("m5", {}).get("sells", 0)
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
        contract = data.get("contract_address")
        
        if data["price"] == 0:
            return False, "No price data"
        
        if data["chain"] != target_chain:
            return False, f"Wrong chain ({data['chain']})"
        
        if data["market_cap"] < settings.min_market_cap:
            return False, f"MC too low ${data['market_cap']:,.0f}"
        if data["market_cap"] > settings.max_market_cap:
            return False, f"MC too high ${data['market_cap']:,.0f}"
        
        if data["liquidity"] < settings.min_liquidity:
            return False, f"Low liquidity ${data['liquidity']:,.0f}"
        
        if data["volume_24h"] < settings.min_volume_24h:
            return False, f"Low volume ${data['volume_24h']:,.0f}"
        
        vol_mc_ratio = data["volume_24h"] / data["market_cap"] if data["market_cap"] > 0 else 0
        if vol_mc_ratio < 0.1:
            return False, f"Low vol/MC ratio {vol_mc_ratio:.1%}"
        
        activity = data["buys_1h"] + data["sells_1h"]
        if activity < 10:
            return False, f"Low activity ({activity} txns/hr)"
        
        buy_ratio = data["buys_1h"] / max(activity, 1)
        if buy_ratio < 0.45:
            return False, f"Weak buy pressure ({buy_ratio:.0%})"
        
        if data["change_1h"] < -15:
            return False, f"Dumping {data['change_1h']:.0f}%"
        
        if data["change_5m"] > 20:
            return False, f"FOMO alert +{data['change_5m']:.0f}% in 5m"
        
        if contract:
            safety = await check_token_safety(contract)
            if not safety["safe"]:
                reasons = ", ".join(safety["reasons"][:2])
                return False, f"Safety: {reasons}"
            
            age_hours = await get_token_age_hours(contract)
            if age_hours < 2:
                return False, f"Too new ({age_hours:.1f}h)"
            if age_hours > 168:
                return False, f"Too old ({age_hours/24:.0f}d)"
        
        return True, "Passed"
    
    def calculate_position_size(self, available_usdc: float, risk_score: int) -> float:
        base_percent = 0.20
        
        if self.consecutive_wins >= 3:
            base_percent = 0.30
        elif self.consecutive_losses >= 2:
            base_percent = 0.10
        
        risk_mult = (100 - risk_score) / 100
        position_percent = base_percent * (0.5 + risk_mult * 0.5)
        
        position_usd = available_usdc * position_percent
        position_usd = max(settings.min_position_usd, min(settings.max_position_usd, position_usd))
        
        return round(position_usd, 2) if position_usd >= 0.50 else 0
    
    def calculate_risk_score(self, signal: dict, data: dict) -> int:
        risk = 50
        
        if data["liquidity"] > 500000:
            risk -= 20
        elif data["liquidity"] > 200000:
            risk -= 10
        elif data["liquidity"] < 100000:
            risk += 15
        
        vol_mc = data["volume_24h"] / data["market_cap"] if data["market_cap"] > 0 else 0
        if vol_mc > 0.5:
            risk -= 10
        elif vol_mc < 0.2:
            risk += 10
        
        activity = data["buys_1h"] + data["sells_1h"]
        buy_ratio = data["buys_1h"] / max(activity, 1)
        if buy_ratio > 0.6:
            risk -= 10
        elif buy_ratio < 0.4:
            risk += 15
        
        if abs(data["change_1h"]) > 30:
            risk += 15
        
        return max(10, min(90, risk))
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        coin = position["coin"]
        data = await self.get_token_data(coin)
        
        if coin not in self.position_highs:
            self.position_highs[coin] = pnl_percent
        else:
            self.position_highs[coin] = max(self.position_highs[coin], pnl_percent)
        
        peak = self.position_highs[coin]
        drawdown = peak - pnl_percent
        
        if data["liquidity"] < 20000:
            return {"should_sell": True, "reason": "⚠️ Liquidity crisis"}
        
        if pnl_percent <= -settings.stop_loss_percent:
            return {"should_sell": True, "reason": f"Stop loss {pnl_percent:.1f}%"}
        
        open_time = position.get("open_time")
        if open_time:
            if isinstance(open_time, str):
                open_time = datetime.fromisoformat(open_time.replace('Z', '+00:00'))
            hours_held = (datetime.now(timezone.utc) - open_time).total_seconds() / 3600
            if hours_held > 2 and -2 < pnl_percent < 3:
                return {"should_sell": True, "reason": f"Time stop ({hours_held:.1f}h flat)"}
        
        if peak >= 20 and drawdown > 8:
            return {"should_sell": True, "reason": f"Trail: +{peak:.0f}%→+{pnl_percent:.0f}%"}
        if peak >= 10 and drawdown > 5:
            return {"should_sell": True, "reason": f"Trail: +{peak:.0f}%→+{pnl_percent:.0f}%"}
        
        if pnl_percent >= settings.take_profit_percent:
            return {"should_sell": True, "reason": f"Take profit +{pnl_percent:.1f}%"}
        
        if data["change_5m"] < -10 and pnl_percent > 0:
            return {"should_sell": True, "reason": "Momentum dying"}
        
        activity = data.get("buys_5m", 0) + data.get("sells_5m", 0)
        if activity > 5:
            sell_ratio = data.get("sells_5m", 0) / activity
            if sell_ratio > 0.7 and pnl_percent > -3:
                return {"should_sell": True, "reason": "Heavy sell pressure"}
        
        return {"should_sell": False, "reason": ""}
    
    async def process_signals(self, signals: list):
        if not settings.trading_enabled:
            return
        if settings.is_daily_loss_limit_hit():
            print("⚠️ Daily loss limit - pausing")
            return
        
        positions = await self.db.get_open_positions()
        if len(positions) >= settings.max_open_positions:
            return
        
        available_usdc = 0
        if dex_trader.initialized:
            balances = await dex_trader.get_balances()
            available_usdc = balances.get("usdc", 0)
            print(f"💰 ${available_usdc:.2f} USDC")
        
        if available_usdc < 0.50:
            return
        
        for signal in signals[:20]:
            coin = signal["coin"].upper().strip()
            
            if settings.is_coin_blacklisted(coin):
                continue
            if settings.is_coin_on_cooldown(coin):
                continue
            if await self.db.has_open_position(coin):
                continue
            
            is_good, reason = await self.is_good_buy(coin, signal)
            if not is_good:
                print(f"⛔ {coin}: {reason}")
                continue
            
            data = await self.get_token_data(coin)
            price = data["price"]
            contract = data["contract_address"]
            
            risk_score = self.calculate_risk_score(signal, data)
            position_usd = self.calculate_position_size(available_usdc, risk_score)
            
            if position_usd < 0.50:
                continue
            
            print(f"✅ {coin} PASS Risk:{risk_score} Liq:${data['liquidity']:,.0f}")
            
            if settings.live_trading and dex_trader.initialized:
                print(f"🔄 BUY ${position_usd:.2f} {coin}")
                result = await dex_trader.swap_usdc_to_token(contract, position_usd)
                
                if not result["success"]:
                    print(f"❌ Failed: {result['error']}")
                    continue
                
                print(f"✅ Bought!")
            else:
                print(f"📝 PAPER BUY: {coin}")
            
            await self.db.open_position({
                "coin": coin,
                "quantity": position_usd / price,
                "buy_price": price,
                "position_usd": position_usd,
                "market_cap": data["market_cap"],
                "risk_score": risk_score,
                "contract_address": contract,
                "chain": data["chain"],
                "signal": signal
            })
            break
        
        settings.record_successful_scan()
    
    async def get_live_price(self, coin: str) -> dict:
        session = await self.get_session()
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        
        data = {"price": 0, "liquidity": 0, "change_5m": 0, "buys_5m": 0, "sells_5m": 0}
        
        try:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/search?q={coin}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    for pair in result.get("pairs", []):
                        symbol = pair.get("baseToken", {}).get("symbol", "").upper()
                        if symbol == coin.upper() and pair.get("chainId") == target_chain:
                            data["price"] = float(pair.get("priceUsd") or 0)
                            data["liquidity"] = float(pair.get("liquidity", {}).get("usd") or 0)
                            data["change_5m"] = float(pair.get("priceChange", {}).get("m5") or 0)
                            txns = pair.get("txns", {})
                            data["buys_5m"] = txns.get("m5", {}).get("buys", 0)
                            data["sells_5m"] = txns.get("m5", {}).get("sells", 0)
                            break
        except:
            pass
        return data
    
    async def check_exit_conditions_live(self):
        positions = await self.db.get_open_positions()
        if not positions:
            return
        
        for pos in positions:
            coin = pos["coin"]
            buy_price = pos["buy_price"]
            contract = pos.get("contract_address")
            
            data = await self.get_live_price(coin)
            current_price = data["price"]
            
            if current_price == 0:
                continue
            
            pnl_percent = ((current_price - buy_price) / buy_price) * 100
            
            self.token_data_cache[coin.upper()] = {
                "data": {**data, "contract_address": contract, "chain": dex_trader.chain},
                "timestamp": datetime.now(timezone.utc)
            }
            
            decision = await self.should_smart_sell(pos, current_price, pnl_percent)
            
            if decision["should_sell"]:
                if settings.live_trading and dex_trader.initialized and contract:
                    print(f"🔄 SELL {coin} {pnl_percent:+.1f}% - {decision['reason']}")
                    result = await dex_trader.swap_token_to_usdc(contract)
                    
                    if not result["success"]:
                        print(f"❌ Sell failed: {result['error']}")
                        continue
                    
                    print(f"✅ Sold!")
                    
                    if pnl_percent > 0:
                        self.consecutive_wins += 1
                        self.consecutive_losses = 0
                    else:
                        self.consecutive_losses += 1
                        self.consecutive_wins = 0
                else:
                    print(f"📝 PAPER SELL: {coin} {pnl_percent:+.1f}%")
                
                if coin in self.position_highs:
                    del self.position_highs[coin]
                
                await self.db.close_position(coin, current_price, decision["reason"])
                if pnl_percent < 0:
                    settings.add_coin_cooldown(coin)
