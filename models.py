from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class Signal(BaseModel):
    coin: str
    current_mentions: int
    baseline_mentions: float
    percent_above_baseline: float
    price_at_signal: float
    current_price: float
    signal_time: datetime
    
class Position(BaseModel):
    coin: str
    quantity: float
    buy_price: float
    current_price: Optional[float] = None
    pnl_percent: Optional[float] = None
    buy_time: datetime
    
class Trade(BaseModel):
    coin: str
    quantity: float
    buy_price: float
    sell_price: float
    pnl_usd: float
    pnl_percent: float
    hold_hours: float
    buy_time: datetime
    sell_time: datetime

class Stats(BaseModel):
    total_pnl: float
    win_rate: float
    total_trades: int
    avg_hold_hours: float

class MentionData(BaseModel):
    coin: str
    source: str
    count: int
    timestamp: datetime

class Settings(BaseModel):
    buzz_threshold: float
    take_profit_percent: float
    stop_loss_percent: float
    max_position_usd: float
    paper_trading: bool
