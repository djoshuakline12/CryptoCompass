from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import asyncio
import traceback
import jwt
import os
from datetime import datetime, timezone

from config import settings
from services.social_scraper import SocialScraper
from services.anomaly_detector import AnomalyDetector
from services.trader import Trader
from services.dex_trader import dex_trader
from database import Database

db = Database()
scraper = SocialScraper()
detector = AnomalyDetector(db)
trader = Trader(db)

security = HTTPBearer(auto_error=False)
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not SUPABASE_JWT_SECRET:
        return None
    if not credentials:
        return None
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        return payload
    except:
        return None

async def background_loop():
    while True:
        try:
            mentions = await scraper.scrape_all_sources()
            await db.update_mention_counts(mentions)
            signals = await detector.detect_signals()
            
            if settings.trading_enabled:
                await trader.process_signals(signals)
                await trader.check_exit_conditions()
            
            settings.record_successful_scan()
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            settings.record_error(str(e))
            await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔧 Initializing CDP DEX trader...")
    await dex_trader.initialize()
    task = asyncio.create_task(background_loop())
    print("🚀 Background trading loop started")
    yield
    task.cancel()

app = FastAPI(title="Crypto Buzz Trader", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "running", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/signals")
async def get_signals(user=Depends(verify_token)):
    try:
        signals = await db.get_active_signals()
        for signal in signals:
            try:
                data = await trader.get_token_data(signal["coin"])
                signal["market_cap"] = data["market_cap"]
                signal["liquidity"] = data["liquidity"]
                signal["volume_24h"] = data["volume_24h"]
                signal["current_price"] = data["price"]
            except:
                signal["current_price"] = 0
        return signals
    except Exception as e:
        print(f"Error in /signals: {e}")
        return []

@app.get("/positions")
async def get_positions(user=Depends(verify_token)):
    try:
        positions = await db.get_open_positions()
        for pos in positions:
            try:
                data = await trader.get_token_data(pos["coin"])
                pos["current_price"] = data["price"] if data["price"] > 0 else pos.get("buy_price", 0)
                pos["liquidity"] = data.get("liquidity", 0)
                pos["volume_24h"] = data.get("volume_24h", 0)
                if pos.get("buy_price") and pos.get("current_price"):
                    pos["pnl_percent"] = ((pos["current_price"] - pos["buy_price"]) / pos["buy_price"]) * 100
                    pos["pnl_usd"] = (pos["current_price"] - pos["buy_price"]) * pos.get("quantity", 0)
                else:
                    pos["pnl_percent"] = 0
                    pos["pnl_usd"] = 0
            except:
                pos["current_price"] = pos.get("buy_price", 0)
                pos["pnl_percent"] = 0
                pos["pnl_usd"] = 0
        return positions
    except Exception as e:
        print(f"Error in /positions: {e}")
        return []

@app.get("/history")
async def get_history(limit: int = 50, user=Depends(verify_token)):
    return await db.get_trade_history(limit)

@app.get("/stats")
async def get_stats(user=Depends(verify_token)):
    try:
        trades = await db.get_trade_history(1000)
        positions = await db.get_open_positions()
        
        unrealized = 0
        for pos in positions:
            try:
                data = await trader.get_token_data(pos["coin"])
                if data["price"]:
                    unrealized += (data["price"] - pos.get("buy_price", 0)) * pos.get("quantity", 0)
            except:
                pass
        
        winners = [t for t in trades if t.get("pnl_percent", 0) > 0]
        
        return {
            "total_realized_pnl": round(settings.realized_pnl, 2),
            "total_unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(settings.realized_pnl + unrealized, 2),
            "daily_pnl": round(settings.daily_pnl, 2),
            "win_rate": round(len(winners) / len(trades) * 100, 1) if trades else 0,
            "total_trades": len(trades),
            "open_positions": len(positions),
            "starting_portfolio": settings.starting_portfolio_usd,
            "current_portfolio": round(settings.total_portfolio_usd + unrealized, 2)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/settings")
async def get_settings(user=Depends(verify_token)):
    return {
        "take_profit_percent": settings.take_profit_percent,
        "stop_loss_percent": settings.stop_loss_percent,
        "max_position_usd": settings.max_position_usd,
        "min_position_usd": settings.min_position_usd,
        "paper_trading": not settings.live_trading,
        "trading_enabled": settings.trading_enabled,
        "min_market_cap": settings.min_market_cap,
        "max_market_cap": settings.max_market_cap,
        "min_liquidity": settings.min_liquidity,
        "min_volume_24h": settings.min_volume_24h,
        "max_open_positions": settings.max_open_positions,
        "starting_portfolio_usd": settings.starting_portfolio_usd,
        "use_ai_sizing": settings.use_ai_sizing,
        "use_ai_smart_sell": settings.use_ai_smart_sell,
        "cooldown_hours": settings.cooldown_hours,
        "max_daily_loss_usd": settings.max_daily_loss_usd
    }

@app.post("/settings")
async def update_settings(new: dict, user=Depends(verify_token)):
    for key in ["take_profit_percent", "stop_loss_percent", "max_position_usd", "min_position_usd",
                "min_market_cap", "max_market_cap", "min_liquidity", "min_volume_24h",
                "max_open_positions", "starting_portfolio_usd", "cooldown_hours", "max_daily_loss_usd"]:
        if key in new:
            setattr(settings, key, new[key])
    if "paper_trading" in new:
        settings.live_trading = not new["paper_trading"]
    if "trading_enabled" in new:
        settings.trading_enabled = new["trading_enabled"]
    if "use_ai_sizing" in new:
        settings.use_ai_sizing = new["use_ai_sizing"]
    if "use_ai_smart_sell" in new:
        settings.use_ai_smart_sell = new["use_ai_smart_sell"]
    return {"status": "updated"}

@app.get("/trading/status")
async def get_trading_status(user=Depends(verify_token)):
    positions = await db.get_open_positions()
    capital_used = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in positions)
    return {
        "trading_enabled": settings.trading_enabled,
        "live_trading": settings.live_trading,
        "open_positions": len(positions),
        "max_positions": settings.max_open_positions,
        "capital_deployed": round(capital_used, 2),
        "capital_available": round(settings.total_portfolio_usd - capital_used, 2),
        "daily_pnl": round(settings.daily_pnl, 2),
        "daily_loss_limit_hit": settings.is_daily_loss_limit_hit(),
        "dex_initialized": dex_trader.initialized
    }

@app.get("/health")
async def get_health():
    return {
        "status": "critical" if settings.is_health_critical() else "healthy",
        "last_scan": settings.last_successful_scan.isoformat() if settings.last_successful_scan else None,
        "errors": settings.consecutive_errors,
        "last_error": settings.last_error,
        "dex_ready": dex_trader.initialized
    }

@app.get("/dex/status")
async def get_dex_status(user=Depends(verify_token)):
    if not dex_trader.initialized:
        return {"initialized": False, "error": "CDP not configured"}
    try:
        balances = await dex_trader.get_balances()
        return {
            "initialized": True,
            "wallet_address": dex_trader.wallet_address,
            "eth_balance": balances.get("eth", 0),
            "usdc_balance": balances.get("usdc", 0),
            "debug": balances.get("error")
        }
    except Exception as e:
        return {"initialized": True, "wallet_address": dex_trader.wallet_address, "error": str(e)}

@app.get("/blacklist")
async def get_blacklist(user=Depends(verify_token)):
    return {
        "blacklisted": list(settings.blacklisted_coins),
        "cooldowns": {c: e.isoformat() for c, e in settings.cooldown_coins.items()}
    }

@app.post("/blacklist/add")
async def add_blacklist(data: dict, user=Depends(verify_token)):
    coin = data.get("coin", "").upper()
    if coin:
        settings.blacklist_coin(coin)
    return {"status": "ok", "coin": coin}

@app.post("/blacklist/remove")
async def remove_blacklist(data: dict, user=Depends(verify_token)):
    coin = data.get("coin", "").upper()
    if coin:
        settings.unblacklist_coin(coin)
    return {"status": "ok", "coin": coin}

@app.post("/cooldown/clear")
async def clear_cooldown(data: dict, user=Depends(verify_token)):
    coin = data.get("coin", "").upper()
    if coin and coin in settings.cooldown_coins:
        del settings.cooldown_coins[coin]
    elif not coin:
        settings.cooldown_coins = {}
    return {"status": "ok"}

@app.post("/trading/start")
async def start_trading(user=Depends(verify_token)):
    settings.trading_enabled = True
    return {"status": "started"}

@app.post("/trading/stop")
async def stop_trading(user=Depends(verify_token)):
    settings.trading_enabled = False
    return {"status": "stopped"}

@app.post("/trading/go-live")
async def enable_live_trading(user=Depends(verify_token)):
    settings.live_trading = True
    settings.trading_enabled = True
    return {"status": "LIVE TRADING ENABLED", "live_trading": True}

@app.post("/trading/paper")
async def enable_paper_trading(user=Depends(verify_token)):
    settings.live_trading = False
    return {"status": "Paper trading enabled", "live_trading": False}

@app.post("/trading/buy")
async def manual_buy(data: dict, user=Depends(verify_token)):
    try:
        coin = data.get("coin", "").upper()
        amount = float(data.get("amount", settings.max_position_usd))
        
        if not coin:
            raise HTTPException(400, "Coin required")
        if settings.is_coin_blacklisted(coin):
            raise HTTPException(400, f"{coin} is blacklisted")
        if await db.has_open_position(coin):
            raise HTTPException(400, f"Already holding {coin}")
        
        token_data = await trader.get_token_data(coin)
        if token_data["price"] == 0:
            raise HTTPException(400, f"Can't get price for {coin}")
        
        quantity = amount / token_data["price"]
        await db.open_position({
            "coin": coin,
            "quantity": quantity,
            "buy_price": token_data["price"],
            "position_usd": amount,
            "market_cap": token_data["market_cap"],
            "signal": {"source": "manual"}
        })
        
        return {"status": "bought", "coin": coin, "quantity": quantity, "price": token_data["price"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/trading/sell")
async def manual_sell(data: dict, user=Depends(verify_token)):
    try:
        coin = data.get("coin", "").upper()
        
        if not coin:
            raise HTTPException(400, "Coin required")
        if not await db.has_open_position(coin):
            raise HTTPException(400, f"No open position for {coin}")
        
        token_data = await trader.get_token_data(coin)
        price = token_data["price"]
        
        if price == 0:
            positions = await db.get_open_positions()
            for p in positions:
                if p["coin"] == coin:
                    price = p.get("buy_price", 0)
                    break
        
        if price == 0:
            raise HTTPException(400, f"Can't determine price for {coin}")
        
        trade = await db.close_position(coin, price, "Manual sell")
        
        if trade is None:
            raise HTTPException(500, "Failed to close position")
        
        return {"status": "sold", "coin": coin, "price": price, "pnl_percent": trade["pnl_percent"], "pnl_usd": trade["pnl_usd"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/force-scan")
async def force_scan(user=Depends(verify_token)):
    mentions = await scraper.scrape_all_sources()
    await db.update_mention_counts(mentions)
    signals = await detector.detect_signals()
    return {"mentions": len(mentions), "signals": len(signals)}

@app.get("/ai-insights")
async def get_ai_insights(user=Depends(verify_token)):
    trades = await db.get_trade_history(100)
    if len(trades) < 5:
        return {"status": "Learning", "trades": len(trades)}
    
    sources = {}
    for t in trades:
        s = t.get("signal_source", "unknown")
        if s not in sources:
            sources[s] = {"wins": 0, "total": 0}
        sources[s]["total"] += 1
        if t.get("pnl_percent", 0) > 0:
            sources[s]["wins"] += 1
    
    rates = {s: round(d["wins"]/d["total"]*100, 1) for s, d in sources.items() if d["total"] > 0}
    best = max(rates, key=rates.get) if rates else "unknown"
    
    return {"status": "Active", "trades": len(trades), "best_source": best, "win_rates": rates}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.post("/dex/withdraw")
async def withdraw_funds(data: dict, user=Depends(verify_token)):
    """Withdraw SOL or USDC to an external wallet"""
    try:
        to_address = data.get("to_address")
        amount = float(data.get("amount", 0))
        token = data.get("token", "usdc").lower()  # "sol" or "usdc"
        
        if not to_address:
            raise HTTPException(400, "to_address required")
        if amount <= 0:
            raise HTTPException(400, "amount must be > 0")
        
        if not dex_trader.initialized:
            raise HTTPException(400, "DEX not initialized")
        
        if dex_trader.chain == "solana":
            from cdp import CdpClient
            
            if token == "sol":
                # Send SOL
                result = await dex_trader.cdp.solana.transfer(
                    from_address=dex_trader.solana_address,
                    to_address=to_address,
                    amount=str(int(amount * 1e9)),  # lamports
                    token="sol"
                )
            else:
                # Send USDC
                USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                result = await dex_trader.cdp.solana.transfer(
                    from_address=dex_trader.solana_address,
                    to_address=to_address,
                    amount=str(int(amount * 1e6)),  # USDC has 6 decimals
                    token=USDC_SOLANA
                )
            
            return {"success": True, "result": str(result)}
        else:
            raise HTTPException(400, "Withdraw only supported for Solana currently")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Withdraw error: {e}")
        raise HTTPException(500, str(e))

@app.get("/dex/wallet-info")
async def get_wallet_info(user=Depends(verify_token)):
    """Get wallet addresses for deposits/withdrawals"""
    return {
        "chain": dex_trader.chain,
        "solana_address": dex_trader.solana_address,
        "base_address": dex_trader.wallet_address,
        "note": "Use /dex/withdraw to send funds to your personal wallet"
    }
