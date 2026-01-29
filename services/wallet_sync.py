import aiohttp
from datetime import datetime, timezone
from typing import List, Dict

class WalletSync:
    """
    Sync database positions with actual wallet holdings
    Ensures we never lose track of tokens
    """
    
    def __init__(self):
        self.last_sync = None
    
    async def get_wallet_tokens(self, wallet_address: str) -> List[Dict]:
        """Get all tokens in wallet from Solscan"""
        tokens = []
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://public-api.solscan.io/account/tokens?account={wallet_address}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        for token in data:
                            address = token.get("tokenAddress", "")
                            amount = float(token.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                            decimals = token.get("tokenAmount", {}).get("decimals", 0)
                            
                            # Skip dust and known tokens (SOL, USDC, USDT)
                            if amount <= 0:
                                continue
                            if address in [
                                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
                                "So11111111111111111111111111111111111111112",   # Wrapped SOL
                            ]:
                                continue
                            
                            # Get token info
                            symbol = token.get("tokenSymbol", "UNKNOWN")
                            name = token.get("tokenName", "Unknown Token")
                            
                            tokens.append({
                                "contract_address": address,
                                "symbol": symbol,
                                "name": name,
                                "amount": amount,
                                "decimals": decimals
                            })
        except Exception as e:
            print(f"Wallet sync error: {e}")
        
        return tokens
    
    async def get_token_value(self, contract_address: str) -> Dict:
        """Get current price and value for a token"""
        result = {"price": 0, "value_usd": 0, "liquidity": 0, "symbol": ""}
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        
                        if pairs:
                            # Find best Solana pair
                            for pair in pairs:
                                if pair.get("chainId") == "solana":
                                    result["price"] = float(pair.get("priceUsd") or 0)
                                    result["liquidity"] = float(pair.get("liquidity", {}).get("usd") or 0)
                                    result["symbol"] = pair.get("baseToken", {}).get("symbol", "")
                                    break
        except:
            pass
        
        return result
    
    async def sync_positions(self, wallet_address: str, db) -> Dict:
        """
        Sync wallet with database:
        - Find tokens in wallet not in DB
        - Add them as 'orphan' positions so bot can manage them
        """
        results = {
            "synced": 0,
            "orphans_found": [],
            "total_orphan_value": 0
        }
        
        # Get actual wallet tokens
        wallet_tokens = await self.get_wallet_tokens(wallet_address)
        
        # Get current DB positions
        db_positions = await db.get_open_positions()
        db_contracts = {p.get("contract_address", "").lower() for p in db_positions}
        
        for token in wallet_tokens:
            contract = token["contract_address"]
            
            # Skip if already tracked
            if contract.lower() in db_contracts:
                continue
            
            # Get current value
            value_info = await self.get_token_value(contract)
            
            if value_info["price"] > 0:
                value_usd = token["amount"] * value_info["price"]
                
                results["orphans_found"].append({
                    "contract": contract,
                    "symbol": value_info["symbol"] or token["symbol"],
                    "amount": token["amount"],
                    "price": value_info["price"],
                    "value_usd": value_usd,
                    "liquidity": value_info["liquidity"]
                })
                results["total_orphan_value"] += value_usd
                
                # Add to database as orphan position
                await db.open_position({
                    "coin": value_info["symbol"] or token["symbol"],
                    "quantity": token["amount"],
                    "buy_price": value_info["price"],  # Use current as buy (unknown actual)
                    "position_usd": value_usd,
                    "market_cap": 0,
                    "risk_score": 90,  # High risk - unknown entry
                    "signal_score": 0,
                    "is_degen": False,
                    "is_orphan": True,  # Mark as orphan
                    "contract_address": contract,
                    "chain": "solana",
                    "signal": {"source": "wallet_sync"}
                })
                results["synced"] += 1
                print(f"📥 Synced orphan: {value_info['symbol']} ${value_usd:.2f}")
        
        self.last_sync = datetime.now(timezone.utc)
        return results

wallet_sync = WalletSync()
