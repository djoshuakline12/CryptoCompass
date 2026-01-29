import aiohttp
import os
from datetime import datetime, timezone
from config import settings
from database import Database
from services.dex_trader import dex_trader
from services.token_safety import check_token_safety, get_token_age_hours
from services.whale_tracker import whale_tracker
from services.volume_detector import volume_detector
from services.market_correlation import market_correlation
from services.alerts import alert_service
from services.signal_sources import signal_sources

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
                        data["contract_address"] = best_pair.get("baseToken", {}).get("address")
                        data["chain"] = best_pair.get("chainId")
        except Exception as e:
            print(f"Token data error for {coin}: {e}")
        
        self.token_data_cache[coin] = {"data": data, "timestamp": datetime.now(timezone.utc)}
        return data
    
    async def get_current_price(self, coin: str) -> float:
        data = await self.get_token_data(coin)
        return data["price"]
    
    async def calculate_signal_score(self, coin: str, contract: str, data: dict) -> dict:
        """Calculate comprehensive signal score using all factors"""
        
        scores = {
            "base": 0,
            "whale": 0,
            "volume_spike": 0,
            "momentum": 0,
            "safety": 0,
            "total": 0,
            "reasons": []
        }
        
        # 1. Whale activity (0-25 points)
        whale_data = whale_tracker.get_whale_score(contract)
        if whale_data["whale_count"] > 0:
            scores["whale"] = min(whale_data["whale_count"] * 10, 25)
            if whale_data["recent"]:
                scores["whale"] += 10
                scores["reasons"].append(f"🐋 {whale_data['whale_count']} whales buying")
        
        # 2. Volume spike (0-25 points)
        if contract:
            vol_data = await volume_detector.check_volume_spike(contract)
            if vol_data["has_spike"]:
                scores["volume_spike"] = min(int(vol_data["spike_multiplier"] * 5), 25)
                scores["reasons"].append(f"📈 {vol_data['spike_multiplier']:.1f}x volume spike")
        
        # 3. Momentum (0-25 points)
        if 5 < data["change_1h"] < 30:
            scores["momentum"] = 15
            scores["reasons"].append(f"🚀 +{data['change_1h']:.0f}% 1h")
        if data["change_5m"] > 3:
            scores["momentum"] += 10
        
        # 4. Buy pressure (0-15 points)
        activity = data["buys_1h"] + data["sells_1h"]
        if activity > 0:
            buy_ratio = data["buys_1h"] / activity
            if buy_ratio > 0.6:
                scores["base"] += 15
                scores["reasons"].append(f"💪 {buy_ratio:.0%} buy pressure")
        
        # 5. Vol/MC ratio (0-10 points)
        if data["market_cap"] > 0:
            vol_mc = data["volume_24h"] / data["market_cap"]
            if vol_mc > 0.5:
                scores["base"] += 10
                scores["reasons"].append("🔥 High volume/MC")
        
        scores["total"] = sum([
            scores["base"],
            scores["whale"],
            scores["volume_spike"],
            scores["momentum"]
        ])
        
        return scores
    
    async def is_good_buy(self, coin: str, signal: dict) -> tuple:
        data = await self.get_token_data(coin)
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        contract = data.get("contract_address") or signal.get("contract_address")
        
        if data["price"] == 0:
            return False, "No price data", 0
        
        if data["chain"] != target_chain:
            return False, f"Wrong chain ({data['chain']})", 0
        
        # Market correlation check
        market = await market_correlation.check_market_conditions()
        if not market["safe_to_buy"]:
            return False, market["warning"], 0
        
        # Basic filters
        if data["market_cap"] < settings.min_market_cap:
            return False, f"MC ${data['market_cap']:,.0f}", 0
        if data["market_cap"] > settings.max_market_cap:
            return False, f"MC too high ${data['market_cap']:,.0f}", 0
        if data["liquidity"] < settings.min_liquidity:
            return False, f"Liq ${data['liquidity']:,.0f}", 0
        if data["volume_24h"] < settings.min_volume_24h:
            return False, f"Vol ${data['volume_24h']:,.0f}", 0
        
        # Activity filter
        activity = data["buys_1h"] + data["sells_1h"]
        if activity < 10:
            return False, f"Low activity ({activity}/hr)", 0
        
        # Not dumping
        if data["change_1h"] < -15:
            return False, f"Dumping {data['change_1h']:.0f}%", 0
        
        # Not FOMO
        if data["change_5m"] > 25:
            return False, f"FOMO +{data['change_5m']:.0f}%/5m", 0
        
        # Safety check
        if contract:
            safety = await check_token_safety(contract)
            if not safety["safe"]:
                reasons = ", ".join(safety["reasons"][:2])
                return False, f"Safety: {reasons}", 0
            
            age_hours = await get_token_age_hours(contract)
            if age_hours < 1:
                return False, f"Too new ({age_hours:.1f}h)", 0
            if age_hours > 168:
                return False, f"Too old ({age_hours/24:.0f}d)", 0
        
        # Calculate comprehensive score
        score_data = await self.calculate_signal_score(coin, contract, data)
        
        # Require minimum score of 30
        if score_data["total"] < 30:
            return False, f"Low score ({score_data['total']})", score_data["total"]
        
        return True, " | ".join(score_data["reasons"]), score_data["total"]
    
    def calculate_position_size(self, available_usdc: float, risk_score: int, signal_score: int) -> float:
        base_percent = 0.20
        
        if self.consecutive_wins >= 3:
            base_percent = 0.30
        elif self.consecutive_losses >= 2:
            base_percent = 0.10
        
        # Boost for high signal scores
        if signal_score >= 60:
            base_percent += 0.10
        
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
            await alert_service.alert_warning("Daily loss limit hit - trading paused")
            return
        
        positions = await self.db.get_open_positions()
        if len(positions) >= settings.max_open_positions:
            return
        
        # Check market conditions first
        market = await market_correlation.check_market_conditions()
        if not market["safe_to_buy"]:
            print(f"⚠️ Market: {market['warning']}")
            return
        
        # Scan whale activity
        await whale_tracker.scan_whale_activity()
        
        available_usdc = 0
        if dex_trader.initialized:
            balances = await dex_trader.get_balances()
            available_usdc = balances.get("usdc", 0)
            print(f"💰 ${available_usdc:.2f} | BTC:{market['btc_change_24h']:+.1f}% SOL:{market['sol_change_1h']:+.1f}%")
        
        if available_usdc < 0.50:
            return
        
        # Use better signal sources
        better_signals = await signal_sources.get_all_signals()
        all_signals = signals + better_signals
        
        # Sort by signal score
        all_signals.sort(key=lambda x: x.get("signal_score", 0), reverse=True)
        
        for signal in all_signals[:30]:
            coin = signal.get("coin", "").upper().strip()
            if not coin:
                continue
            
            if settings.is_coin_blacklisted(coin):
                continue
            if settings.is_coin_on_cooldown(coin):
                continue
            if await self.db.has_open_position(coin):
                continue
            
            is_good, reason, signal_score = await self.is_good_buy(coin, signal)
            if not is_good:
                print(f"⛔ {coin}: {reason}")
                continue
            
            data = await self.get_token_data(coin)
            price = data["price"]
            contract = data["contract_address"] or signal.get("contract_address")
            
            risk_score = self.calculate_risk_score(signal, data)
            position_usd = self.calculate_position_size(available_usdc, risk_score, signal_score)
            
            if position_usd < 0.50:
                continue
            
            print(f"✅ {coin} Score:{signal_score} Risk:{risk_score} | {reason}")
            
            if settings.live_trading and dex_trader.initialized:
                print(f"🔄 BUY ${position_usd:.2f} {coin}")
                result = await dex_trader.swap_usdc_to_token(contract, position_usd)
                
                if not result["success"]:
                    print(f"❌ Failed: {result['error']}")
                    continue
                
                print(f"✅ Bought!")
                await alert_service.alert_buy(coin, position_usd, price, reason)
            else:
                print(f"📝 PAPER BUY: {coin}")
            
            await self.db.open_position({
                "coin": coin,
                "quantity": position_usd / price,
                "buy_price": price,
                "position_usd": position_usd,
                "market_cap": data["market_cap"],
                "risk_score": risk_score,
                "signal_score": signal_score,
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
            pnl_usd = pnl_percent / 100 * (buy_price * pos.get("quantity", 0))
            
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
                    await alert_service.alert_sell(coin, pnl_percent, pnl_usd, decision["reason"])
                    
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
