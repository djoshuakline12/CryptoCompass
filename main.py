import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from database import Database
from services.trader import Trader
from services.signals import SignalAggregator
from services.dex_trader import dex_trader

db = Database()
trader = Trader(db)
signals = SignalAggregator()
security = HTTPBearer(auto_error=False)

latest_signals = []
last_scan_time = None

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    return True

async def signal_scan_loop():
    """Scan for new signals every 30 seconds"""
    global latest_signals, last_scan_time
    while True:
        try:
            latest_signals = await signals.get_all_signals()
            unique = {s["coin"]: s for s in latest_signals}
            print(f"📊 {len(unique)} unique signals")
            print(f"🎯 {len(latest_signals)} signals")
            
            await trader.process_signals(list(unique.values()))
            last_scan_time = datetime.now(timezone.utc)
            
        except Exception as e:
            print(f"Signal scan error: {e}")
            settings.record_error(str(e))
        
        await asyncio.sleep(30)  # Scan for new signals every 30s

async def position_monitor_loop():
    """Monitor open positions every 5 seconds for quick exits"""
    while True:
        try:
            await trader.check_exit_conditions_live()
        except Exception as e:
            print(f"Position monitor error: {e}")
        
        await asyncio.sleep(5)  # Check positions every 5s

@asynccontextmanager
async def lifespan(app: FastAPI):
    # db already initializes in __init__
    await dex_trader.initialize()
    
    # Start both loops
    asyncio.create_task(signal_scan_loop())
    asyncio.create_task(position_monitor_loop())
    print("🚀 Trading loops started (signals: 30s, positions: 5s)")
    
    yield
    
    if trader.session:
        await trader.session.close()

app = FastAPI(title="CryptoCompass", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "running",
        "signals": len(latest_signals),
        "last_scan": last_scan_time.isoformat() if last_scan_time else None,
        "chain": dex_trader.chain
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "last_scan": last_scan_time.isoformat() if last_scan_time else None,
        "errors": settings.consecutive_errors,
        "last_error": settings.last_error,
        "dex_ready": dex_trader.initialized
    }

@app.get("/signals")
async def get_signals(user=Depends(verify_token)):
    return latest_signals[:50]

@app.get("/positions")
async def get_positions(user=Depends(verify_token)):
    positions = await db.get_open_positions()
    for pos in positions:
        price = await trader.get_current_price(pos["coin"])
        if price and pos["buy_price"]:
            pos["current_price"] = price
            pos["pnl_percent"] = ((price - pos["buy_price"]) / pos["buy_price"]) * 100
            pos["pnl_usd"] = pos["pnl_percent"] / 100 * (pos["buy_price"] * pos["quantity"])
            
            data = await trader.get_token_data(pos["coin"])
            pos["liquidity"] = data.get("liquidity", 0)
            pos["volume_24h"] = data.get("volume_24h", 0)
    return positions

@app.get("/history")
async def get_history(user=Depends(verify_token)):
    return await db.get_trade_history(limit=50)

@app.get("/stats")
async def get_stats(user=Depends(verify_token)):
    positions = await db.get_open_positions()
    history = await db.get_trade_history(limit=100)
    
    total_pnl = sum(h.get("pnl_usd", 0) or 0 for h in history)
    wins = [h for h in history if (h.get("pnl_usd") or 0) > 0]
    
    # Calculate capital deployed in open positions
    capital_deployed = sum(
        (p.get("buy_price", 0) or 0) * (p.get("quantity", 0) or 0) 
        for p in positions
    )
    
    # Get actual USDC balance
    balances = await dex_trader.get_balances()
    capital_available = balances.get("usdc", 0)
    
    # Calculate unrealized PnL
    unrealized_pnl = 0
    for p in positions:
        price = await trader.get_current_price(p["coin"])
        if price and p.get("buy_price"):
            unrealized_pnl += (price - p["buy_price"]) * p.get("quantity", 0)
    
    return {
        "open_positions": len(positions),
        "total_trades": len(history),
        "total_pnl_usd": round(total_pnl, 2),
        "win_rate": round(len(wins) / len(history) * 100, 1) if history else 0,
        "portfolio_value": round(capital_deployed + capital_available, 2),
        "daily_pnl": round(settings.daily_pnl, 2),
        "starting_capital": settings.starting_portfolio_usd, "startingCapital": settings.starting_portfolio_usd,
        "current_portfolio": round(capital_deployed + capital_available, 2),
        "capital_deployed": round(capital_deployed, 2), "capitalDeployed": round(capital_deployed, 2),
        "capital_available": round(capital_available, 2), "capitalAvailable": round(capital_available, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "realized_pnl": round(total_pnl, 2),
        "max_positions": settings.max_open_positions
    }

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
async def update_settings(data: dict, user=Depends(verify_token)):
    for key, value in data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "updated"}

@app.get("/trading/status")
async def trading_status(user=Depends(verify_token)):
    return {
        "live_trading": settings.live_trading,
        "trading_enabled": settings.trading_enabled,
        "dex_initialized": dex_trader.initialized,
        "chain": dex_trader.chain
    }

@app.post("/trading/go-live")
async def go_live(user=Depends(verify_token)):
    settings.live_trading = True
    return {"status": "LIVE TRADING ENABLED", "live_trading": True}

@app.post("/trading/paper")
async def go_paper(user=Depends(verify_token)):
    settings.live_trading = False
    return {"status": "PAPER TRADING", "live_trading": False}

@app.post("/trading/pause")
async def pause_trading(user=Depends(verify_token)):
    settings.trading_enabled = False
    return {"status": "paused"}

@app.post("/trading/resume")
async def resume_trading(user=Depends(verify_token)):
    settings.trading_enabled = True
    return {"status": "resumed"}

@app.get("/blacklist")
async def get_blacklist(user=Depends(verify_token)):
    return list(settings.blacklisted_coins)

@app.post("/blacklist/{coin}")
async def add_to_blacklist(coin: str, user=Depends(verify_token)):
    settings.blacklist_coin(coin.upper())
    return {"status": "blacklisted", "coin": coin.upper()}

@app.delete("/blacklist/{coin}")
async def remove_from_blacklist(coin: str, user=Depends(verify_token)):
    settings.unblacklist_coin(coin.upper())
    return {"status": "removed", "coin": coin.upper()}

@app.get("/dex/status")
async def get_dex_status(user=Depends(verify_token)):
    try:
        balances = await dex_trader.get_balances()
        return {
            "initialized": dex_trader.initialized,
            "wallet_address": dex_trader.solana_address,
            "chain": dex_trader.chain,
            "sol_balance": balances.get("sol", 0),
            "usdc_balance": balances.get("usdc", 0)
        }
    except Exception as e:
        return {"initialized": dex_trader.initialized, "error": str(e)}

@app.get("/ai-insights")
async def get_ai_insights(user=Depends(verify_token)):
    positions = await db.get_open_positions()
    insights = []
    
    for pos in positions:
        data = await trader.get_token_data(pos["coin"])
        price = data["price"]
        if price and pos["buy_price"]:
            pnl = ((price - pos["buy_price"]) / pos["buy_price"]) * 100
            
            peak = trader.position_highs.get(pos["coin"], pnl)
            
            insights.append({
                "coin": pos["coin"],
                "pnl_percent": round(pnl, 2),
                "peak_pnl": round(peak, 2),
                "momentum_1h": data.get("change_1h", 0),
                "momentum_5m": data.get("change_5m", 0),
                "liquidity": data.get("liquidity", 0),
                "volume_24h": data.get("volume_24h", 0),
                "buy_pressure": round(data["buys_1h"] / max(data["buys_1h"] + data["sells_1h"], 1) * 100, 1)
            })
    
    return insights

# Backtest endpoint
from services.backtester import backtester

@app.get("/backtest")
async def run_backtest(user=Depends(verify_token)):
    """Run backtest on recent trending tokens"""
    # Get some tokens to test
    from services.signal_sources import signal_sources
    signals = await signal_sources.get_all_signals()
    tokens = [s.get("contract_address") for s in signals if s.get("contract_address")][:10]
    
    result = await backtester.run_backtest(tokens)
    return result

@app.get("/market/status")
async def get_market_status(user=Depends(verify_token)):
    """Get current market conditions"""
    from services.market_correlation import market_correlation
    return await market_correlation.check_market_conditions()
