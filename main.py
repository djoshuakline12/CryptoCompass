from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime

from config import settings
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
    # Enrich with market cap if missing
    for signal in signals:
        if signal.get("market_cap", 0) == 0:
            mc = await trader.get_market_cap(signal["coin"])
            signal["market_cap"] = mc
    return signals

@app.get("/positions")
async def get_positions() -> list[dict]:
    positions = await db.get_open_positions()
    for pos in positions:
        current_price = await trader.get_current_price(pos["coin"])
        pos["current_price"] = current_price
        pos["pnl_percent"] = ((current_price - pos["buy_price"]) / pos["buy_price"]) * 100 if pos["buy_price"] else 0
        pos["pnl_usd"] = (current_price - pos["buy_price"]) * pos["quantity"] if pos["buy_price"] else 0
    return positions

@app.get("/history")
async def get_history(limit: int = 50) -> list[dict]:
    return await db.get_trade_history(limit)

@app.get("/stats")
async def get_stats() -> dict:
    trades = await db.get_trade_history(limit=1000)
    positions = await db.get_open_positions()
    
    if not trades:
        return {
            "total_pnl": 0,
            "win_rate": 0,
            "total_trades": 0,
            "avg_hold_hours": 0,
            "open_positions": len(positions),
            "capital_deployed": sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in positions)
        }
    
    winners = [t for t in trades if t["pnl_percent"] > 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)
    
    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(len(winners) / len(trades) * 100, 1),
        "total_trades": len(trades),
        "avg_hold_hours": round(sum(t["hold_hours"] for t in trades) / len(trades), 1),
        "open_positions": len(positions),
        "capital_deployed": round(sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in positions), 2)
    }

@app.get("/settings")
async def get_settings() -> dict:
    return {
        "buzz_threshold": settings.buzz_threshold,
        "take_profit_percent": settings.take_profit_percent,
        "stop_loss_percent": settings.stop_loss_percent,
        "max_position_usd": settings.max_position_usd,
        "min_position_usd": settings.min_position_usd,
        "paper_trading": not settings.live_trading,
        "trading_enabled": settings.trading_enabled,
        "min_market_cap": settings.min_market_cap,
        "max_market_cap": settings.max_market_cap,
        "max_open_positions": settings.max_open_positions,
        "total_portfolio_usd": settings.total_portfolio_usd,
        "use_ai_sizing": settings.use_ai_sizing
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
    if "min_position_usd" in new_settings:
        settings.min_position_usd = new_settings["min_position_usd"]
    if "paper_trading" in new_settings:
        settings.live_trading = not new_settings["paper_trading"]
    if "trading_enabled" in new_settings:
        settings.trading_enabled = new_settings["trading_enabled"]
    if "min_market_cap" in new_settings:
        settings.min_market_cap = new_settings["min_market_cap"]
    if "max_market_cap" in new_settings:
        settings.max_market_cap = new_settings["max_market_cap"]
    if "max_open_positions" in new_settings:
        settings.max_open_positions = new_settings["max_open_positions"]
    if "total_portfolio_usd" in new_settings:
        settings.total_portfolio_usd = new_settings["total_portfolio_usd"]
    if "use_ai_sizing" in new_settings:
        settings.use_ai_sizing = new_settings["use_ai_sizing"]
    return {"status": "updated"}

@app.get("/trading/status")
async def get_trading_status() -> dict:
    positions = await db.get_open_positions()
    capital_used = sum(p.get("buy_price", 0) * p.get("quantity", 0) for p in positions)
    return {
        "trading_enabled": settings.trading_enabled,
        "live_trading": settings.live_trading,
        "open_positions": len(positions),
        "max_positions": settings.max_open_positions,
        "capital_used": round(capital_used, 2),
        "capital_available": round(settings.total_portfolio_usd - capital_used, 2),
        "total_portfolio": settings.total_portfolio_usd,
        "use_ai_sizing": settings.use_ai_sizing
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
    market_cap = await trader.get_market_cap(coin)
    quantity = float(amount) / price
    
    await db.open_position({
        "coin": coin,
        "quantity": quantity,
        "buy_price": price,
        "position_usd": amount,
        "market_cap": market_cap,
        "signal": {"source": "manual"}
    })
    
    print(f"✅ MANUAL BUY: {quantity:.4f} {coin} @ ${price:.4f}")
    return {"status": "bought", "coin": coin, "quantity": quantity, "price": price, "market_cap": market_cap}

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
            "avg_risk_score": 0,
            "recommendation": "Gather more trade data for AI insights"
        }
    
    source_performance = {}
    risk_performance = {"low": [], "medium": [], "high": []}
    
    for trade in trades:
        source = trade.get("signal_source", "unknown")
        risk = trade.get("risk_score", 50)
        pnl = trade.get("pnl_percent", 0)
        
        if source not in source_performance:
            source_performance[source] = {"wins": 0, "total": 0, "pnl": 0}
        source_performance[source]["total"] += 1
        source_performance[source]["pnl"] += pnl
        if pnl > 0:
            source_performance[source]["wins"] += 1
        
        if risk < 30:
            risk_performance["low"].append(pnl)
        elif risk < 60:
            risk_performance["medium"].append(pnl)
        else:
            risk_performance["high"].append(pnl)
    
    win_rates = {s: round(d["wins"]/d["total"]*100, 1) for s, d in source_performance.items() if d["total"] > 0}
    best_source = max(win_rates, key=win_rates.get) if win_rates else "unknown"
    
    return {
        "status": "Active",
        "trades_analyzed": len(trades),
        "best_source": best_source,
        "win_rate_by_source": win_rates,
        "avg_pnl_by_risk": {
            "low": round(sum(risk_performance["low"]) / len(risk_performance["low"]), 2) if risk_performance["low"] else 0,
            "medium": round(sum(risk_performance["medium"]) / len(risk_performance["medium"]), 2) if risk_performance["medium"] else 0,
            "high": round(sum(risk_performance["high"]) / len(risk_performance["high"]), 2) if risk_performance["high"] else 0
        },
        "recommendation": f"Focus on {best_source} signals" if best_source != "unknown" else "Continue gathering data"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
