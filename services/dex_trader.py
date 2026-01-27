import os
import asyncio
import aiohttp
from datetime import datetime, timezone
from config import settings

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC = "https://mainnet.base.org"

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.account = None
        self.initialized = False
        self.wallet_address = None
        
    async def initialize(self):
        if self.initialized:
            return True
            
        cdp_key = os.getenv("CDP_API_KEY_NAME", "")
        cdp_secret = os.getenv("CDP_API_KEY_SECRET", "")
        
        if not cdp_key or not cdp_secret:
            print("⚠️  CDP API keys not configured - paper trading only")
            return False
        
        try:
            from cdp import CdpClient
            
            os.environ["CDP_API_KEY_ID"] = cdp_key
            os.environ["CDP_API_KEY_SECRET"] = cdp_secret
            
            self.cdp = CdpClient()
            await self.cdp.__aenter__()
            print("✅ CDP SDK connected")
            
            account_name = os.getenv("CDP_ACCOUNT_NAME", "CryptoCompass")
            
            self.account = await self.cdp.evm.get_or_create_account(name=account_name)
            
            self.wallet_address = self.account.address
            print(f"✅ Account ready on Base: {self.wallet_address}")
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        if not self.wallet_address:
            return {"eth": 0, "usdc": 0, "error": "No wallet"}
        
        result = {"eth": 0, "usdc": 0}
        
        try:
            async with aiohttp.ClientSession() as session:
                eth_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getBalance",
                    "params": [self.wallet_address, "latest"],
                    "id": 1
                }
                async with session.post(BASE_RPC, json=eth_payload) as resp:
                    data = await resp.json()
                    if "result" in data:
                        wei = int(data["result"], 16)
                        result["eth"] = wei / 1e18
                
                usdc_data = "0x70a08231" + self.wallet_address[2:].zfill(64)
                usdc_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": USDC_BASE, "data": usdc_data}, "latest"],
                    "id": 2
                }
                async with session.post(BASE_RPC, json=usdc_payload) as resp:
                    data = await resp.json()
                    if "result" in data and data["result"] != "0x":
                        raw = int(data["result"], 16)
                        result["usdc"] = raw / 1e6
                        
        except Exception as e:
            print(f"Balance error: {e}")
            result["error"] = str(e)
        
        return result
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float) -> dict:
        """Swap USDC to a token on Base"""
        if not self.initialized or not self.account:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Swapping ${amount_usdc} USDC for token {token_address}")
            
            # Convert to smallest unit (USDC has 6 decimals)
            amount_raw = int(amount_usdc * 1e6)
            
            # Use CDP trade API
            trade = await self.cdp.evm.trade(
                address=self.wallet_address,
                from_token=USDC_BASE,
                to_token=token_address,
                amount=str(amount_raw),
                slippage_percent=1.0
            )
            
            print(f"✅ Swap executed: {trade}")
            return {
                "success": True,
                "tx_hash": getattr(trade, 'transaction_hash', None),
                "amount_in": amount_usdc,
                "token_address": token_address
            }
            
        except Exception as e:
            print(f"❌ Swap error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def swap_token_to_usdc(self, token_address: str, amount_tokens: float = None) -> dict:
        """Swap token back to USDC (sell all if amount not specified)"""
        if not self.initialized or not self.account:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Selling token {token_address} for USDC")
            
            # If no amount specified, sell entire balance
            if amount_tokens is None:
                # Get token balance
                token_data = "0x70a08231" + self.wallet_address[2:].zfill(64)
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [{"to": token_address, "data": token_data}, "latest"],
                        "id": 1
                    }
                    async with session.post(BASE_RPC, json=payload) as resp:
                        data = await resp.json()
                        if "result" in data and data["result"] != "0x":
                            amount_raw = int(data["result"], 16)
                        else:
                            return {"success": False, "error": "Could not get token balance"}
            else:
                # Assume 18 decimals for most tokens
                amount_raw = int(amount_tokens * 1e18)
            
            if amount_raw == 0:
                return {"success": False, "error": "No tokens to sell"}
            
            # Use CDP trade API
            trade = await self.cdp.evm.trade(
                address=self.wallet_address,
                from_token=token_address,
                to_token=USDC_BASE,
                amount=str(amount_raw),
                slippage_percent=2.0  # Higher slippage for selling small caps
            )
            
            print(f"✅ Sell executed: {trade}")
            return {
                "success": True,
                "tx_hash": getattr(trade, 'transaction_hash', None),
                "token_address": token_address
            }
            
        except Exception as e:
            print(f"❌ Sell error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

dex_trader = DexTrader()
