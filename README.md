# Crypto Buzz Trader

Automated crypto trading based on early social media buzz detection.

## How It Works

1. **Scrapes** social sources (Reddit, LunarCrush) every 2 minutes
2. **Tracks** mention counts per coin over time
3. **Detects** anomalies when mentions spike above baseline (e.g., 200% above normal)
4. **Buys** automatically when early buzz detected
5. **Sells** at take profit (default 15%) or stop loss (default 8%)

## Project Structure

```
├── main.py                 # FastAPI app + background trading loop
├── config.py               # Settings and environment variables
├── models.py               # Pydantic data models
├── database.py             # Supabase integration
├── services/
│   ├── social_scraper.py   # Reddit, LunarCrush data collection
│   ├── anomaly_detector.py # Buzz spike detection
│   └── trader.py           # Exchange integration + execution
├── requirements.txt
└── .env.example
```

## Setup

### 1. Database (Supabase)

Create a free project at [supabase.com](https://supabase.com) and run this SQL:

```sql
-- Mention counts over time
create table mentions (
  id bigserial primary key,
  coin text not null,
  source text not null,
  count integer not null,
  timestamp timestamptz default now()
);

-- Detected buzz signals
create table signals (
  id bigserial primary key,
  coin text not null,
  current_mentions integer,
  baseline_mentions float,
  percent_above_baseline float,
  timestamp timestamptz default now()
);

-- Open and closed positions
create table positions (
  id bigserial primary key,
  coin text not null,
  quantity float not null,
  buy_price float not null,
  open_time timestamptz default now(),
  status text default 'open'
);

-- Completed trades
create table trades (
  id bigserial primary key,
  coin text not null,
  quantity float,
  buy_price float,
  sell_price float,
  pnl_usd float,
  pnl_percent float,
  hold_hours float,
  buy_time timestamptz,
  sell_time timestamptz default now()
);

-- Indexes for performance
create index idx_mentions_coin_time on mentions(coin, timestamp);
create index idx_positions_status on positions(status);
```

### 2. API Keys

Copy `.env.example` to `.env` and fill in:

- **Supabase**: Get URL and anon key from project settings
- **Reddit**: Create app at reddit.com/prefs/apps (choose "script" type)
- **LunarCrush**: Free API key at lunarcrush.com
- **Exchange**: Get from your exchange (Binance, Coinbase, etc.)

### 3. Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python main.py
```

API will be at `http://localhost:8000`

### 4. Deploy to Railway

1. Push code to GitHub
2. Connect repo to [railway.app](https://railway.app)
3. Add environment variables in Railway dashboard
4. Deploy

Railway will auto-detect Python and run `uvicorn main:app --host 0.0.0.0 --port $PORT`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/signals` | GET | Current buzz signals |
| `/positions` | GET | Open positions |
| `/history` | GET | Completed trades |
| `/stats` | GET | Performance stats |
| `/settings` | GET/POST | View/update trading params |
| `/force-scan` | POST | Manually trigger scan cycle |

## Connecting to Lovable Frontend

In your Lovable project, set an environment variable:

```
API_URL=https://your-railway-app.up.railway.app
```

Then make fetch calls like:

```javascript
const signals = await fetch(`${import.meta.env.VITE_API_URL}/signals`).then(r => r.json());
```

## Configuration

Edit `config.py` or use the `/settings` endpoint:

| Setting | Default | Description |
|---------|---------|-------------|
| `buzz_threshold` | 200 | % above baseline to trigger buy |
| `take_profit_percent` | 15 | Sell when up this % |
| `stop_loss_percent` | 8 | Sell when down this % |
| `max_position_usd` | 100 | Max $ per trade |
| `live_trading` | false | Paper trading by default |

## Paper Trading

The system runs in paper trading mode by default. It will:
- Execute all logic
- Log trades to database
- Track P&L

But it won't actually place orders on the exchange until you set `live_trading = True`.

## Adding More Data Sources

Add new scraper methods in `services/social_scraper.py` and call them from `scrape_all_sources()`.

Good candidates:
- Telegram groups (telethon library)
- Twitter/X (expensive API or scraping)
- Discord servers (discord.py)
- 4chan /biz/ board
- StockTwits crypto section
