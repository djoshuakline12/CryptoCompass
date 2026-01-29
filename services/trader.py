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
from services.pumpfun_scanner import pumpfun_scanner
from services.dev_tracker import dev_tracker
from services.tx_simulator import tx_simulator

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
    
    def is_degen_signal(self, signal: dict) -> bool:
        source = signal.get("source", "")
        return source in ["pumpfun_new", "pumpfun_graduating"]
    
    async def is_good_buy_safe(self, coin: str, signal: dict, data: dict, contract: str) -> tuple:
        if data["market_cap"] < settings.min_market_cap:
            return False, f"MC ${data['market_cap']:,.0f}"
        if data["market_cap"] > settings.max_market_cap:
            return False, f"MC too high ${data['market_cap']:,.0f}"
        if data["liquidity"] < settings.min_liquidity:
            return False, f"Liq ${data['liquidity']:,.0f}"
        if data["volume_24h"] < settings.min_volume_24h:
            return False, f"Vol ${data['volume_24h']:,.0f}"
        
        activity = data["buys_1h"] + data["sells_1h"]
        if activity < 20:
            return False, f"Low activity ({activity}/hr)"
        
        buy_ratio = data["buys_1h"] / max(activity, 1)
        if buy_ratio < 0.5:
            return False, f"Weak buys ({buy_ratio:.0%})"
        
        if contract:
            safety = await check_token_safety(contract)
            if not safety["safe"]:
                reasons = ", ".join(safety["reasons"][:2])
                return False, f"Safety: {reasons}"
            
            age_hours = await get_token_age_hours(contract)
            if age_hours < 1:
                return False, f"Too new ({age_hours:.1f}h)"
            if age_hours > 168:
                return False, f"Too old ({age_hours/24:.0f}d)"
            
            sim = await tx_simulator.can_sell_token(contract, dex_trader.solana_address or "")
            if not sim["can_sell"]:
                return False, f"Honeypot: {sim['error']}"
            
            dev_check = await dev_tracker.is_dev_selling(contract)
            if dev_check["is_selling"]:
                return False, "Dev selling!"
        
        return True, "Safe ✓"
    
    async def is_good_buy_degen(self, coin: str, signal: dict, contract: str) -> tuple:
        if not settings.degen_enabled:
            return False, "Degen disabled"
        
        market_cap = signal.get("market_cap", 0)
        
        if market_cap < settings.degen_min_market_cap:
            return False, f"MC too low ${market_cap:,.0f}"
        if market_cap > settings.degen_max_market_cap:
            return False, f"MC too high ${market_cap:,.0f}"
        
        age_min = signal.get("age_minutes", 0)
        if age_min < 3:
            return False, f"Too fresh ({age_min:.0f}m)"
        if age_min > 120:
            return False, f"Too old ({age_min:.0f}m)"
        
        if contract:
            dev_check = await dev_tracker.is_dev_selling(contract)
            if dev_check["is_selling"]:
                return False, "Dev selling!"
        
        if signal.get("source") == "pumpfun_graduating":
            return True, "🚀 Graduating!"
        
        return True, "Degen ✓"
    
    async def is_good_buy(self, coin: str, signal: dict) -> tuple:
        data = await self.get_token_data(coin)
        target_chain = dex_trader.chain if dex_trader.initialized else "solana"
        contract = data.get("contract_address") or signal.get("contract_address")
        
        if data["price"] == 0 and not self.is_degen_signal(signal):
            return False, "No price data", 0, False
        
        if data["chain"] and data["chain"] != target_chain:
            return False, f"Wrong chain ({data['chain']})", 0, False
        
        market = await market_correlation.check_market_conditions()
        if not market["safe_to_buy"]:
            return False, market["warning"], 0, False
        
        if data["change_1h"] < -10:
            return False, f"Dumping {data['change_1h']:.0f}%", 0, False
        
        if data["change_5m"] > 15:
            return False, f"FOMO {data['change_5m']:.0f}%/5m", 0, False
        
        is_degen = self.is_degen_signal(signal)
        
        if is_degen:
            is_good, reason = await self.is_good_buy_degen(coin, signal, contract)
            signal_score = 70 if is_good else 0
        else:
            is_good, reason = await self.is_good_buy_safe(coin, signal, data, contract)
            if is_good:
                score_data = await self.calculate_signal_score(coin, contract, data)
                signal_score = score_data["total"]
                reason = " | ".join(score_data["reasons"]) if score_data["reasons"] else reason
            else:
                signal_score = 0
        
        return is_good, reason, signal_score, is_degen
    
    async def calculate_signal_score(self, coin: str, contract: str, data: dict) -> dict:
        scores = {"base": 0, "whale": 0, "volume_spike": 0, "momentum": 0, "total": 0, "reasons": []}
        
        whale_data = whale_tracker.get_whale_score(contract)
        if whale_data["whale_count"] > 0:
            scores["whale"] = min(whale_data["whale_count"] * 10, 25)
            if whale_data["recent"]:
                scores["whale"] += 10
                scores["reasons"].append(f"🐋 {whale_data['whale_count']} whales")
        
        if contract:
            vol_data = await volume_detector.check_volume_spike(contract)
            if vol_data["has_spike"]:
                scores["volume_spike"] = min(int(vol_data["spike_multiplier"] * 5), 25)
                scores["reasons"].append(f"📈 {vol_data['spike_multiplier']:.1f}x vol")
        
        if 5 < data["change_1h"] < 25:
            scores["momentum"] = 15
            scores["reasons"].append(f"🚀 +{data['change_1h']:.0f}%")
        if data["change_5m"] > 2:
            scores["momentum"] += 10
        
        activity = data["buys_1h"] + data["sells_1h"]
        if activity > 0:
            buy_ratio = data["buys_1h"] / activity
            if buy_ratio > 0.55:
                scores["base"] += 15
                scores["reasons"].append(f"💪 {buy_ratio:.0%} buys")
        
        scores["total"] = sum([scores["base"], scores["whale"], scores["volume_spike"], scores["momentum"]])
        return scores
    
    def calculate_position_size(self, available_usdc: float, risk_score: int, signal_score: int, is_degen: bool) -> float:
        if is_degen:
            return min(settings.degen_max_position_usd, available_usdc * 0.15)
        
        base_percent = 0.20
        
        if self.consecutive_wins >= 3:
            base_percent = 0.25
        elif self.consecutive_losses >= 2:
            base_percent = 0.15
        
        if signal_score >= 60:
            base_percent += 0.05
        
        risk_mult = (100 - risk_score) / 100
        position_percent = base_percent * (0.5 + risk_mult * 0.5)
        
        position_usd = available_usdc * position_percent
        position_usd = max(settings.min_position_usd, min(settings.max_position_usd, position_usd))
        
        return round(position_usd, 2) if position_usd >= 0.50 else 0
    
    def calculate_risk_score(self, signal: dict, data: dict) -> int:
        risk = 50
        
        if data["liquidity"] > 500000:
            risk -= 15
        elif data["liquidity"] > 200000:
            risk -= 10
        
        vol_mc = data["volume_24h"] / data["market_cap"] if data["market_cap"] > 0 else 0
        if vol_mc > 0.5:
            risk -= 10
        
        activity = data["buys_1h"] + data["sells_1h"]
        buy_ratio = data["buys_1h"] / max(activity, 1)
        if buy_ratio > 0.6:
            risk -= 10
        elif buy_ratio < 0.45:
            risk += 10
        
        return max(10, min(90, risk))
    
    async def should_smart_sell(self, position: dict, current_price: float, pnl_percent: float) -> dict:
        """
        IMPROVED EXIT STRATEGY:
        - Quick profit at +5% 
        - Trailing stop from +3% (protect small gains)
        - Momentum-based exits
        - Tight stop loss at -4%
        """
        coin = position["coin"]
        data = await self.get_token_data(coin)
        is_degen = position.get("is_degen", False)
        
        # Track peak P&L
        if coin not in self.position_highs:
            self.position_highs[coin] = pnl_percent
        else:
            self.position_highs[coin] = max(self.position_highs[coin], pnl_percent)
        
        peak = self.position_highs[coin]
        drawdown = peak - pnl_percent
        
        # === EMERGENCY EXITS ===
        if data["liquidity"] < 10000:
            return {"should_sell": True, "reason": "⚠️ Liquidity crisis"}
        
        # Dev selling - immediate exit
        contract = position.get("contract_address")
        if contract and dev_tracker.is_known_dev_seller(contract):
            return {"should_sell": True, "reason": "🚨 Dev selling!"}
        
        # === STOP LOSS ===
        stop_loss = -15 if is_degen else -4  # Tighter stop for safe trades
        if pnl_percent <= stop_loss:
            return {"should_sell": True, "reason": f"Stop loss {pnl_percent:.1f}%"}
        
        # === TAKE PROFIT ===
        take_profit = 20 if is_degen else 5  # Quick profit for safe trades
        if pnl_percent >= take_profit:
            return {"should_sell": True, "reason": f"🎯 Take profit +{pnl_percent:.1f}%"}
        
        # === TRAILING STOPS (protect gains) ===
        # Once we're up 3%, don't let it go red
        if peak >= 3 and pnl_percent <= 0.5:
            return {"should_sell": True, "reason": f"Protect gains: was +{peak:.1f}%"}
        
        # Once up 5%, keep at least 2%
        if peak >= 5 and pnl_percent <= 2:
            return {"should_sell": True, "reason": f"Trail: +{peak:.1f}%→+{pnl_percent:.1f}%"}
        
        # Once up 10%, keep at least 5%
        if peak >= 10 and pnl_percent <= 5:
            return {"should_sell": True, "reason": f"Trail: +{peak:.1f}%→+{pnl_percent:.1f}%"}
        
        # Once up 20%, keep at least 12%
        if peak >= 20 and pnl_percent <= 12:
            return {"should_sell": True, "reason": f"Trail: +{peak:.1f}%→+{pnl_percent:.1f}%"}
        
        # === TIME STOP ===
        open_time = position.get("open_time")
        if open_time:
            if isinstance(open_time, str):
                open_time = datetime.fromisoformat(open_time.replace('Z', '+00:00'))
            hours_held = (datetime.now(timezone.utc) - open_time).total_seconds() / 3600
            
            # Exit flat positions after 30 min
            if hours_held > 0.5 and -1 < pnl_percent < 2:
                return {"should_sell": True, "reason": f"Time stop ({hours_held*60:.0f}m, flat)"}
        
        # === MOMENTUM EXITS ===
        # Price tanking in last 5 min while we're still positive - get out
        if data["change_5m"] < -5 and pnl_percent > 0:
            return {"should_sell": True, "reason": f"Momentum dying (-{abs(data['change_5m']):.0f}%/5m)"}
        
        # Heavy sell pressure
        activity = data.get("buys_5m", 0) + data.get("sells_5m", 0)
        if activity > 10:
            sell_ratio = data.get("sells_5m", 0) / activity
            if sell_ratio > 0.65 and pnl_percent > -2:
                return {"should_sell": True, "reason": f"Sell pressure ({sell_ratio:.0%} sells)"}
        
        return {"should_sell": False, "reason": ""}
    
    async def get_degen_exposure(self, positions: list) -> float:
        total = 0
        for pos in positions:
            if pos.get("is_degen", False):
                price = await self.get_current_price(pos["coin"])
                total += price * pos.get("quantity", 0)
        return total
    
    async def process_signals(self, signals: list):
        if not settings.trading_enabled:
            return
        if settings.is_daily_loss_limit_hit():
            print("⚠️ Daily loss limit - pausing")
            await alert_service.alert_warning("Daily loss limit hit")
            return
        
        positions = await self.db.get_open_positions()
        if len(positions) >= settings.max_open_positions:
            return
        
        market = await market_correlation.check_market_conditions()
        if not market["safe_to_buy"]:
            print(f"⚠️ Market: {market['warning']}")
            return
        
        await whale_tracker.scan_whale_activity()
        
        available_usdc = 0
        if dex_trader.initialized:
            balances = await dex_trader.get_balances()
            available_usdc = balances.get("usdc", 0)
            print(f"💰 ${available_usdc:.2f} | BTC:{market['btc_change_24h']:+.1f}% SOL:{market['sol_change_1h']:+.1f}%")
        
        if available_usdc < 0.50:
            return
        
        total_portfolio = available_usdc + sum(
            pos.get("buy_price", 0) * pos.get("quantity", 0) for pos in positions
        )
        degen_exposure = await self.get_degen_exposure(positions)
        degen_budget = settings.get_degen_budget(total_portfolio, degen_exposure)
        
        better_signals = await signal_sources.get_all_signals()
        pumpfun_signals = await pumpfun_scanner.get_all_signals() if settings.degen_enabled else []
        all_signals = signals + better_signals + pumpfun_signals
        
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
            
            is_good, reason, signal_score, is_degen = await self.is_good_buy(coin, signal)
            
            if not is_good:
                print(f"⛔ {coin}: {reason}")
                continue
            
            if is_degen and degen_budget < settings.degen_max_position_usd:
                print(f"⛔ {coin}: Degen budget exhausted")
                continue
            
            data = await self.get_token_data(coin)
            price = data["price"] or signal.get("price", 0.0001)
            contract = data["contract_address"] or signal.get("contract_address")
            
            risk_score = self.calculate_risk_score(signal, data)
            position_usd = self.calculate_position_size(available_usdc, risk_score, signal_score, is_degen)
            
            if position_usd < 0.50:
                continue
            
            tier = "🎰 DEGEN" if is_degen else "✅ SAFE"
            print(f"{tier} {coin} Score:{signal_score} | {reason}")
            
            if settings.live_trading and dex_trader.initialized:
                print(f"🔄 BUY ${position_usd:.2f} {coin}")
                result = await dex_trader.swap_usdc_to_token(contract, position_usd)
                
                if not result["success"]:
                    print(f"❌ Failed: {result['error']}")
                    continue
                
                print(f"✅ Bought!")
                await alert_service.alert_buy(coin, position_usd, price, f"{tier} | {reason}")
            
            await self.db.open_position({
                "coin": coin,
                "quantity": position_usd / price if price > 0 else 0,
                "buy_price": price,
                "position_usd": position_usd,
                "market_cap": data.get("market_cap") or signal.get("market_cap", 0),
                "risk_score": risk_score,
                "signal_score": signal_score,
                "is_degen": is_degen,
                "contract_address": contract,
                "chain": data.get("chain", "solana"),
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
                is_degen = pos.get("is_degen", False)
                tier = "🎰" if is_degen else "📈"
                
                if settings.live_trading and dex_trader.initialized and contract:
                    print(f"🔄 SELL {tier} {coin} {pnl_percent:+.1f}% - {decision['reason']}")
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
                
                if coin in self.position_highs:
                    del self.position_highs[coin]
                
                await self.db.close_position(coin, current_price, decision["reason"])
                if pnl_percent < 0:
                    settings.add_coin_cooldown(coin)
