import os
import anthropic

async def should_sell(position: dict, token_data: dict) -> dict:
    """
    AI-powered sell decision that considers momentum, not just fixed percentages.
    Returns: {"sell": bool, "reason": str, "urgency": "high"|"medium"|"low"}
    """
    
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    pnl_percent = position.get("pnl_percent", 0)
    current_price = position.get("current_price", 0)
    buy_price = position.get("buy_price", 0)
    
    # Token metrics
    volume_24h = token_data.get("volume_24h", 0)
    liquidity = token_data.get("liquidity", 0)
    price_change_1h = token_data.get("price_change_1h", 0)
    price_change_24h = token_data.get("price_change_24h", 0)
    
    prompt = f"""You are a meme coin trading analyst. Decide if we should SELL or HOLD this position.

POSITION:
- Coin: {position.get('coin')}
- Buy price: ${buy_price:.8f}
- Current price: ${current_price:.8f}
- P&L: {pnl_percent:+.1f}%
- Time held: {position.get('hold_time', 'unknown')}

CURRENT METRICS:
- 24h Volume: ${volume_24h:,.0f}
- Liquidity: ${liquidity:,.0f}
- 1h price change: {price_change_1h:+.1f}%
- 24h price change: {price_change_24h:+.1f}%

DECISION FRAMEWORK:
- If losing money AND momentum is negative (falling volume, negative price changes) → SELL (cut losses)
- If losing money BUT momentum is positive (rising volume, price recovering) → HOLD (might recover)
- If profitable AND momentum is strong (high volume, positive changes) → HOLD (let it run!)
- If profitable BUT momentum dying (falling volume, price stalling) → SELL (take profits)
- If liquidity is dropping fast → SELL (rug pull risk)
- If up 50%+ with weakening momentum → SELL (secure the bag)
- If up 100%+ → Consider partial sell strategy

CRITICAL: Meme coins can 10x-100x. Don't sell winners too early if momentum is strong.
But also: Meme coins can go to zero. Don't hold losers hoping for recovery if momentum is dead.

Respond in this exact JSON format:
{{"sell": true/false, "reason": "brief explanation", "urgency": "high/medium/low"}}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        import json
        result_text = response.content[0].text
        
        # Parse JSON from response
        start = result_text.find('{')
        end = result_text.rfind('}') + 1
        if start >= 0 and end > start:
            result = json.loads(result_text[start:end])
            print(f"   🤖 AI: {'SELL' if result['sell'] else 'HOLD'} - {result['reason']}")
            return result
        
        return {"sell": False, "reason": "Could not parse AI response", "urgency": "low"}
        
    except Exception as e:
        print(f"   AI error: {e}")
        # Fallback to simple rules
        if pnl_percent <= -15:
            return {"sell": True, "reason": "Stop loss (fallback)", "urgency": "high"}
        if pnl_percent >= 50 and price_change_1h < -5:
            return {"sell": True, "reason": "Taking profits, momentum fading (fallback)", "urgency": "medium"}
        return {"sell": False, "reason": "Holding (fallback)", "urgency": "low"}


async def calculate_trailing_stop(position: dict) -> float:
    """
    Dynamic trailing stop based on gains.
    The more you're up, the tighter the stop (to protect profits).
    """
    pnl = position.get("pnl_percent", 0)
    
    if pnl < 0:
        # Losing: wider stop, give it room
        return -15  # Sell if drops to -15%
    elif pnl < 20:
        # Small gains: moderate stop
        return pnl - 10  # Stop 10% below current
    elif pnl < 50:
        # Good gains: tighter stop
        return pnl - 15  # Stop 15% below current (locks in some profit)
    elif pnl < 100:
        # Great gains: protect profits
        return pnl - 20  # Stop 20% below (still locks in 30%+ if at 50%)
    else:
        # Massive gains (100%+): let it ride but protect
        return pnl - 25  # Stop 25% below (still locks in 75%+ profit)
