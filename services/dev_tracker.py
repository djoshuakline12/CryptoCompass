import aiohttp
import os
from datetime import datetime, timezone

class DevWalletTracker:
    def __init__(self):
        self.dev_wallets = {}  # contract -> deployer wallet
        self.dev_selling = set()  # contracts where dev is selling
        self.dev_holdings = {}  # contract -> dev still holds tokens
    
    async def get_deployer_wallet(self, contract_address: str) -> str:
        """Get the wallet that created/deployed the token"""
        if contract_address in self.dev_wallets:
            return self.dev_wallets[contract_address]
        
        try:
            async with aiohttp.ClientSession() as session:
                # Try Solscan token meta
                url = f"https://public-api.solscan.io/token/meta?tokenAddress={contract_address}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        creator = data.get("creator", "")
                        if creator:
                            self.dev_wallets[contract_address] = creator
                            return creator
                
                # Fallback: try Helius
                helius_key = os.getenv("HELIUS_API_KEY", "")
                if helius_key:
                    url = f"https://api.helius.xyz/v0/token-metadata?api-key={helius_key}"
                    async with session.post(url, json={"mintAccounts": [contract_address]}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data and len(data) > 0:
                                authority = data[0].get("onChainAccountInfo", {}).get("accountInfo", {}).get("data", {}).get("parsed", {}).get("info", {}).get("mintAuthority", "")
                                if authority:
                                    self.dev_wallets[contract_address] = authority
                                    return authority
        except:
            pass
        
        return ""
    
    async def check_dev_holdings(self, contract_address: str, dev_wallet: str) -> dict:
        """Check if dev still holds tokens"""
        result = {"holds_tokens": False, "balance_percent": 0}
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://public-api.solscan.io/account/tokens?account={dev_wallet}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for token in data:
                            if token.get("tokenAddress") == contract_address:
                                result["holds_tokens"] = True
                                # Get percentage of supply
                                amount = float(token.get("tokenAmount", {}).get("uiAmount", 0))
                                # We'd need total supply to calc percent, estimate for now
                                result["balance_percent"] = min(amount * 100, 100)
                                break
        except:
            pass
        
        return result
    
    async def is_dev_selling(self, contract_address: str) -> dict:
        """Check if developer is actively selling tokens"""
        result = {
            "is_selling": False,
            "dev_wallet": "",
            "recent_sells": 0,
            "warning": None
        }
        
        # Quick check if we already know
        if contract_address in self.dev_selling:
            return {"is_selling": True, "dev_wallet": "", "recent_sells": 1, "warning": "Known dev seller!"}
        
        dev_wallet = await self.get_deployer_wallet(contract_address)
        if not dev_wallet:
            return result
        
        result["dev_wallet"] = dev_wallet
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get dev's recent transactions
                url = f"https://public-api.solscan.io/account/transactions?account={dev_wallet}&limit=30"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        sell_count = 0
                        for tx in (data if isinstance(data, list) else []):
                            # Look for sells of this specific token
                            tx_hash = tx.get("txHash", "")
                            
                            # Check transaction details for token transfers
                            detail_url = f"https://public-api.solscan.io/transaction/{tx_hash}"
                            try:
                                async with session.get(detail_url, timeout=aiohttp.ClientTimeout(total=5)) as detail_resp:
                                    if detail_resp.status == 200:
                                        detail = await detail_resp.json()
                                        
                                        # Look for token transfer FROM dev wallet
                                        for transfer in detail.get("tokenTransfers", []):
                                            if (transfer.get("source") == dev_wallet and 
                                                transfer.get("token") == contract_address):
                                                sell_count += 1
                            except:
                                continue
                        
                        result["recent_sells"] = sell_count
                        
                        if sell_count >= 2:
                            result["is_selling"] = True
                            result["warning"] = f"Dev sold {sell_count}x recently!"
                            self.dev_selling.add(contract_address)
        except:
            pass
        
        return result
    
    def is_known_dev_seller(self, contract_address: str) -> bool:
        """Quick check without API calls"""
        return contract_address in self.dev_selling

dev_tracker = DevWalletTracker()
