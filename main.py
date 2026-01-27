from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime

from config import settings
from models import Settings, Signal, Position, Trade, Stats
from services.social_scraper import SocialScraper
from services.anomaly_detector import AnomalyDetector
from services.trader import Trader
from database import Database

db = Database()
scraper = SocialScraper()
detector = AnomalyDetector(db)
trader = Trader(db)

async def background_loop():
    while True:
        try:
            mentions = await scraper.scrape_all_sources()
            await db.update_mention_counts(mentions)
            signals = await detector.detect_signals()
            
            if settings.trading_enabled:
                await trader.process_signals(signals)
                await trader.check_exit_conditions()
            
            await asyncio.sleep(120)
        except Exception as e:
            print(f"Error in background loop: {e}")
            await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
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
)

@app.get("/")
async def root():
    return {"status": "running", "paper_trading": not settings.live_trading}

@app.get("/signals")
async def get_signals() -> list[dict]:
    signals = await db.get_active_signals()
    return signals

@app.get("/positions")
async def get_positions() -> list[dict]:
    positions = await db.get_open_positions()
    for pos in positions:
        current_price = await trader.get_current_price(pos["coin"])
        pos["current_price"] = current_price
        pos["pnl_percent"] = ((current_price - pos["buy_price"]) / pos["buy_price"]) * 100 if pos["buy_price"] else 0
    return positions

@app.get("/history")
async def get_history(limit: int = 50) -> list[dict]:
    trades = await db.get_trade_history(limit)
    return trades

@app.get("/stats")
async def get_stats() -> dict:
    trades = await db.get_trade_history(limit=1000)
    if not trades:
        return {"total_pnl": 0, "total_pnl_percent": 0, "win_rate": 0, "total_trades": 0, "avg_hold_hours": 0}
    
    winners = [t for t in trades if t["pnl_percent"] > 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    
    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(len(winners) / len(trades) * 100, 1),
        "total_trades": len(trades),
        "avg_hold_hours": round(sum(t["hold_hours"] for t in trades) / len(trades), 1)
    }

@app.get("/settings")
async def get_settings() -> dict:
    return {
        "buzz_threshold": settings.buzz_threshold,
        "take_profit_percent": settings.take_profit_percent,
        "stop_loss_percent": settings.stop_loss_percent,
        "max_position_usd": settings.max_position_usd,
        "paper_trading": not settings.live_trading,
        "trading_enabled": settings.trading_enabled,
        "min_market_cap": settings.min_market_cap,
        "max_market_cap": settings.max_market_cap
    }

@app.post("/settings")
async def update_settings(new_settings: dict) -> dict:
    if "buzz_threshold" in new_settings:
        settings.buzz_threshold = new_settings["buzz_threshold"]
    if "take_profit_percent" in new_settings:
        settings.take_profit_percent = new_settings["take_profit_percent"]
    if "stop_loss_percent" in new_settings:
        settings.stop_loss_percent = new_settings["stop_loss_percent"]
    if "max_position_usd" in new_settings:
        settings.max_position_usd = new_settings["max_position_usd"]
    if "paper_trading" in new_settings:
        settings.live_trading = not new_settings["paper_trading"]
    if "trading_enabled" in new_settings:
        settings.trading_enabled = new_settings["trading_enabled"]
    if "min_market_cap" in new_settings:
        settings.min_market_cap = new_settings["min_market_cap"]
    if "max_market_cap" in new_settings:
        settings.max_market_cap = new_settings["max_market_cap"]
    return {"status": "updated"}

@app.get("/trading/status")
async def get_trading_status() -> dict:
    positions = await db.get_open_positions()
    return {
        "trading_enabled": settings.trading_enabled,
        "live_trading": settings.live_trading,
        "open_positions": len(positions),
        "max_positions": 3
    }

@app.post("/trading/start")
async def start_trading():
    settings.trading_enabled = True
    return {"status": "trading started", "trading_enabled": True}

@app.post("/trading/stop")
async def stop_trading():
    settings.trading_enabled = False
    return {"status": "trading stopped", "trading_enabled": False}

@app.post("/trading/buy")
async def manual_buy(data: dict) -> dict:
    coin = data.get("coin")
    amount = data.get("amount", settings.max_position_usd)
    
    if not coin:
        raise HTTPException(status_code=400, detail="Coin required")
    
    if await db.has_open_position(coin):
        raise HTTPException(status_code=400, detail=f"Already have position in {coin}")
    
    price = await trader.get_current_price(coin)
    quantity = float(amount) / price
    
    await db.open_position({
        "coin": coin,
        "quantity": quantity,
        "buy_price": price,
        "signal": {"source": "manual"}
    })
    
    print(f"✅ MANUAL BUY: {quantity:.4f} {coin} @ ${price:.4f}")
    return {"status": "bought", "coin": coin, "quantity": quantity, "price": price}

@app.post("/trading/sell")
async def manual_sell(data: dict) -> dict:
    coin = data.get("coin")
    
    if not coin:
        raise HTTPException(status_code=400, detail="Coin required")
    
    if not await db.has_open_position(coin):
        raise HTTPException(status_code=400, detail=f"No open position for {coin}")
    
    price = await trader.get_current_price(coin)
    trade = await db.close_position(coin, price)
    
    print(f"✅ MANUAL SELL: {coin} @ ${price:.4f} | PnL: {trade['pnl_percent']:+.1f}%")
    return {"status": "sold", "coin": coin, "price": price, "pnl_percent": trade["pnl_percent"], "pnl_usd": trade["pnl_usd"]}

@app.post("/force-scan")
async def force_scan() -> dict:
    mentions = await scraper.scrape_all_sources()
    await db.update_mention_counts(mentions)
    signals = await detector.detect_signals()
    return {"mentions_collected": len(mentions), "signals_found": len(signals)}

@app.get("/ai-insights")
async def get_ai_insights() -> dict:
    trades = await db.get_trade_history(limit=100)
    
    if len(trades) < 5:
        return {
            "status": "Learning...",
            "trades_analyzed": len(trades),
            "best_source": "Not enough data",
            "best_time": "Not enough data",
            "recommended_threshold": settings.buzz_threshold,
            "win_rate_by_source": {}
        }
    
    source_performance = {}
    for trade in trades:
        source = trade.get("signal_source", "unknown")
        if source not in source_performance:
            source_performance[source] = {"wins": 0, "total": 0}
        source_performance[source]["total"] += 1
        if trade["pnl_percent"] > 0:
            source_performance[source]["wins"] += 1
    
    win_rates = {s: round(d["wins"]/d["total"]*100, 1) for s, d in source_performance.items() if d["total"] > 0}
    best_source = max(win_rates, key=win_rates.get) if win_rates else "unknown"
    
    return {
        "status": "Active",
        "trades_analyzed": len(trades),
        "best_source": best_source,
        "best_time": "UTC 14:00-18:00",
        "recommended_threshold": settings.buzz_threshold,
        "win_rate_by_source": win_rates
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
