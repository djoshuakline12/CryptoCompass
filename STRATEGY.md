# CryptoCompass Trading Strategy v2.0

## Realistic Goals
- Target: 1-2% daily average (still ~1000% annually)
- Accept: Some days -5%, some days +10%
- Win rate goal: 55-60% of trades profitable

## Core Strategy: "Smart Momentum"

### 1. SIGNAL QUALITY (Most Important)
Only trade coins that pass ALL filters:

**On-Chain Verification:**
- [ ] Liquidity locked or burned (check via RugCheck.xyz API)
- [ ] Contract not a honeypot (can actually sell)
- [ ] Top 10 holders own <50% supply
- [ ] Not a clone of major token name

**Market Metrics:**
- Liquidity: $100k - $5M (enough to exit, not too established)
- Market Cap: $500k - $20M (room to grow)
- 24h Volume: >50% of market cap (active trading)
- Age: 1-7 days old (new but not brand new scam)

**Momentum Signals:**
- Price up 10-50% in last 4h (momentum, not exhausted)
- Volume increasing (not decreasing)
- More buys than sells in last hour
- Social mentions increasing

### 2. ENTRY RULES
- Only enter on pullbacks (not at local highs)
- Wait for 5-10% dip after initial pump
- Confirm volume still strong during dip

### 3. EXIT RULES (Critical for profitability)

**Take Profit (scaled):**
- Sell 50% at +8% (lock in profit)
- Sell 25% at +15%
- Let 25% ride with trailing stop

**Stop Loss:**
- Hard stop: -6%
- Trailing stop: -4% from peak once profitable

**Time Stop:**
- Exit after 2 hours if flat (opportunity cost)

### 4. POSITION SIZING (Kelly Criterion)
- Risk max 5% of portfolio per trade
- Reduce size after 2 consecutive losses
- Increase size after 3 consecutive wins

### 5. RISK MANAGEMENT
- Max 2 positions at once (correlated)
- Stop trading for day after -10% daily loss
- Never trade first 2 hours after major BTC move

### 6. WHALE TRACKING (Best Edge)
Track wallets that:
- Made 10+ profitable meme trades
- Have >70% win rate
- Buy when they buy (within 1 minute)

## Expected Results
- Win Rate: 55%
- Average Win: +10%
- Average Loss: -5%
- Expected Value per trade: +2.75%
- With 2 trades/day: +5.5% daily (before fees)
- After 1% fees: +3.5% daily net

## Implementation Priority

1. **RugCheck Integration** - Verify contracts before buying
2. **Whale Wallet Tracking** - Copy successful traders
3. **Partial Exits** - Take profit in stages
4. **Time-Based Exits** - Don't hold losers hoping
5. **Better Signals** - On-chain data > social mentions
