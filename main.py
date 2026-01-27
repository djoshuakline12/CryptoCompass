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

# Global instances
db = Database()
scraper = SocialScraper()
detector = AnomalyDetector(db)
trader = Trader(db)

async def background_loop():
    """Main loop that runs continuously - scrapes, detects, trades"""
    while True:
        try:
            # 1. Scrape social mentions
            mentions = await scraper.scrape_all_sources()
            
            # 2. Update mention counts in database
            await db.update_mention_counts(mentions)
            
            # 3. Detect anomalies (early buzz)
            signals = await detector.detect_signals()
            
            # 4. Execute trades based on signals
            if settings.trading_enabled:
                await trader.process_signals(signals)
                await trader.check_exit_conditions()
            
            # Wait before next cycle (2 minutes)
            await asyncio.sleep(120)
            
        except Exception as e:
            print(f"Error in background loop: {e}")
            await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: begin background trading loop
    task = asyncio.create_task(background_loop())
    print("🚀 Background trading loop started")
    yield
    # Shutdown: cancel background task
    task.cancel()

app = FastAPI(title="Crypto Buzz Trader", lifespan=lifespan)

# Allow Lovable frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ API ENDPOINTS ============

@app.get("/")
async def root():
    return {"status": "running", "paper_trading": not settings.live_trading}

@app.get("/signals")
async def get_signals() -> list[dict]:
    """Get coins currently showing early buzz"""
    signals = await db.get_active_signals()
    return signals

@app.get("/positions")
async def get_positions() -> list[dict]:
    """Get currently held positions"""
    positions = await db.get_open_positions()
    
    # Enrich with current prices
    for pos in positions:
        current_price = await trader.get_current_price(pos["coin"])
        pos["current_price"] = current_price
        pos["pnl_percent"] = ((current_price - pos["buy_price"]) / pos["buy_price"]) * 100
    
    return positions

@app.get("/history")
async def get_history(limit: int = 50) -> list[dict]:
    """Get completed trades"""
    trades = await db.get_trade_history(limit)
    return trades

@app.get("/stats")
async def get_stats() -> dict:
    """Get overall performance statistics"""
    trades = await db.get_trade_history(limit=1000)
    
    if not trades:
        return {
            "total_pnl": 0,
            "total_pnl_percent": 0,
            "win_rate": 0,
            "total_trades": 0,
            "avg_hold_hours": 0
        }
    
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
    """Get current trading settings"""
    return {
        "buzz_threshold": settings.buzz_threshold,
        "take_profit_percent": settings.take_profit_percent,
        "stop_loss_percent": settings.stop_loss_percent,
        "max_position_usd": settings.max_position_usd,
        "paper_trading": not settings.live_trading
    }

@app.post("/settings")
async def update_settings(new_settings: dict) -> dict:
    """Update trading settings"""
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
    
    return {"status": "updated"}

@app.post("/force-scan")
async def force_scan() -> dict:
    """Manually trigger a scan cycle"""
    mentions = await scraper.scrape_all_sources()
    await db.update_mention_counts(mentions)
    signals = await detector.detect_signals()
    return {"mentions_collected": len(mentions), "signals_found": len(signals)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
