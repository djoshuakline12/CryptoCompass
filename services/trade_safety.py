import aiohttp
from typing import Dict

class TradeSafety:
    """
    Additional safety checks before executing trades
    """
    
    # Known fee tokens (take % on transfer)
    FEE_TOKENS = set([
        # Add known fee tokens here as discovered
    ])
    
    async def check_slippage(self, contract: str, amount_usd: float) -> Dict:
        """
        Check expected slippage before trading
        Returns estimated output and slippage %
        """
        result = {
            "safe": True,
            "slippage_percent": 0,
            "warning": None
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get quote from Jupiter
                amount_raw = int(amount_usd * 1e6)  # USDC decimals
                url = f"https://public.jupiterapi.com/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={contract}&amount={amount_raw}&slippageBps=100"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        price_impact = float(data.get("priceImpactPct", 0) or 0)
                        result["slippage_percent"] = abs(price_impact)
                        
                        # Warn if slippage > 2%
                        if abs(price_impact) > 2:
                            result["safe"] = False
                            result["warning"] = f"High slippage: {price_impact:.1f}%"
                        
                        # Check if route exists
                        if not data.get("outAmount"):
                            result["safe"] = False
                            result["warning"] = "No route found"
        except Exception as e:
            result["warning"] = f"Quote failed: {str(e)[:50]}"
        
        return result
    
    async def is_fee_token(self, contract: str) -> Dict:
        """
        Check if token has transfer fees
        """
        result = {
            "has_fee": False,
            "fee_percent": 0
        }
        
        if contract in self.FEE_TOKENS:
            result["has_fee"] = True
            result["fee_percent"] = 5  # Assume 5% if known
            return result
        
        # Could add API check here for unknown tokens
        # For now, rely on simulation
        
        return result
    
    async def validate_trade(self, contract: str, amount_usd: float, is_buy: bool) -> Dict:
        """
        Full validation before executing trade
        """
        result = {
            "safe": True,
            "warnings": [],
            "should_proceed": True
        }
        
        # Check slippage
        slippage = await self.check_slippage(contract, amount_usd)
        if not slippage["safe"]:
            result["warnings"].append(slippage["warning"])
            if slippage["slippage_percent"] > 5:  # >5% = don't trade
                result["safe"] = False
                result["should_proceed"] = False
        
        # Check fee token
        fee_check = await self.is_fee_token(contract)
        if fee_check["has_fee"]:
            result["warnings"].append(f"Fee token: {fee_check['fee_percent']}%")
            result["safe"] = False
            result["should_proceed"] = False
        
        return result

trade_safety = TradeSafety()
