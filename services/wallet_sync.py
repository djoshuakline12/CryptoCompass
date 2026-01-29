import aiohttp
import os
from datetime import datetime, timezone
from typing import List, Dict

class WalletSync:
    def __init__(self):
        self.last_sync = None
        self.helius_key = os.getenv("HELIUS_API_KEY", "")
    
    async def get_wallet_tokens(self, wallet_address: str) -> List[Dict]:
        """Get all tokens in wallet using Helius"""
        tokens = []
        
        try:
            async with aiohttp.ClientSession() as session:
                # Use Helius for reliable data
                if self.helius_key:
                    url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/balances?api-key={self.helius_key}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            
                            for token in data.get("tokens", []):
                                address = token.get("mint", "")
                                amount = float(token.get("amount", 0) or 0)
                                decimals = token.get("decimals", 0)
                                
                                # Adjust for decimals
                                if decimals > 0:
                                    amount = amount / (10 ** decimals)
                                
                                # Skip dust and stablecoins
                                if amount <= 0:
                                    continue
                                if address in [
                                    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                                    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
                                    "So11111111111111111111111111111111111111112",   # Wrapped SOL
                                ]:
                                    continue
                                
                                tokens.append({
                                    "contract_address": address,
                                    "symbol": token.get("symbol", "UNKNOWN"),
                                    "name": token.get("name", "Unknown"),
                                    "amount": amount,
                                    "decimals": decimals
                                })
                else:
                    # Fallback to DexScreener token search
                    print("No Helius key, using fallback")
                    
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
        """Sync wallet with database"""
        results = {
            "synced": 0,
            "orphans_found": [],
            "total_orphan_value": 0
        }
        
        wallet_tokens = await self.get_wallet_tokens(wallet_address)
        db_positions = await db.get_open_positions()
        db_contracts = {p.get("contract_address", "").lower() for p in db_positions if p.get("contract_address")}
        
        for token in wallet_tokens:
            contract = token["contract_address"]
            
            if contract.lower() in db_contracts:
                continue
            
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
                results["synced"] += 1
                print(f"📥 Found orphan: {value_info['symbol']} ${value_usd:.2f}")
        
        self.last_sync = datetime.now(timezone.utc)
        return results

wallet_sync = WalletSync()
