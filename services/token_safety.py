import aiohttp

async def check_token_safety(contract_address: str) -> dict:
    """
    Check if token is safe to trade using RugCheck API
    Returns: {"safe": bool, "reasons": [], "score": 0-100}
    """
    result = {
        "safe": False,
        "reasons": [],
        "score": 0,
        "liquidity_locked": False,
        "honeypot": True,
        "top_holders_percent": 100
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # RugCheck.xyz API
            url = f"https://api.rugcheck.xyz/v1/tokens/{contract_address}/report"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    risks = data.get("risks", [])
                    risk_names = [r.get("name", "") for r in risks]
                    
                    # Check for critical risks
                    critical_risks = [
                        "Honeypot",
                        "Mint Authority Enabled", 
                        "Freeze Authority Enabled",
                        "Low Liquidity",
                        "Unlocked Liquidity"
                    ]
                    
                    found_critical = [r for r in risk_names if any(c.lower() in r.lower() for c in critical_risks)]
                    
                    if not found_critical:
                        result["safe"] = True
                        result["score"] = 80
                    else:
                        result["reasons"] = found_critical
                        result["score"] = 20
                    
                    # Check top holders
                    top_holders = data.get("topHolders", [])
                    if top_holders:
                        total_percent = sum(h.get("pct", 0) for h in top_holders[:10])
                        result["top_holders_percent"] = total_percent
                        if total_percent > 50:
                            result["safe"] = False
                            result["reasons"].append(f"Top 10 holders own {total_percent:.0f}%")
                    
                    # Check if liquidity is locked
                    if "liquidity" in str(data).lower() and "lock" in str(data).lower():
                        result["liquidity_locked"] = True
                        result["score"] += 10
                    
                    result["honeypot"] = "honeypot" in str(risks).lower()
                    
    except Exception as e:
        result["reasons"].append(f"Check failed: {str(e)[:50]}")
        result["safe"] = False
    
    return result


async def get_token_age_hours(contract_address: str) -> float:
    """Get token age in hours from first transaction"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        created = pairs[0].get("pairCreatedAt", 0)
                        if created:
                            import time
                            age_ms = time.time() * 1000 - created
                            return age_ms / (1000 * 60 * 60)  # Convert to hours
    except:
        pass
    return 0
