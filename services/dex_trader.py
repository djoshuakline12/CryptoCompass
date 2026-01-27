import os
import asyncio
import aiohttp
from datetime import datetime, timezone

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.account = None
        self.solana_account = None
        self.initialized = False
        self.wallet_address = None
        self.solana_address = None
        self.chain = "solana"
        
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
            
            try:
                self.solana_account = await self.cdp.solana.get_or_create_account(name=f"{account_name}-SOL")
                self.solana_address = self.solana_account.address
                print(f"✅ Solana account ready: {self.solana_address}")
                
                # Print available methods for debugging
                methods = [m for m in dir(self.solana_account) if not m.startswith('_')]
                print(f"   Account methods: {methods}")
                
                solana_methods = [m for m in dir(self.cdp.solana) if not m.startswith('_')]
                print(f"   Solana client methods: {solana_methods}")
                
                self.chain = "solana"
            except Exception as e:
                print(f"⚠️  Solana account error: {e}")
                self.account = await self.cdp.evm.get_or_create_account(name=account_name)
                self.wallet_address = self.account.address
                print(f"✅ Base account ready: {self.wallet_address}")
                self.chain = "base"
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        result = {"sol": 0, "usdc": 0, "eth": 0, "chain": self.chain}
        
        try:
            if self.chain == "solana" and self.solana_address:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getBalance",
                        "params": [self.solana_address]
                    }
                    async with session.post("https://api.mainnet-beta.solana.com", json=payload) as resp:
                        data = await resp.json()
                        if "result" in data:
                            lamports = data["result"].get("value", 0)
                            result["sol"] = lamports / 1e9
                    
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenAccountsByOwner",
                        "params": [
                            self.solana_address,
                            {"mint": USDC_SOLANA},
                            {"encoding": "jsonParsed"}
                        ]
                    }
                    async with session.post("https://api.mainnet-beta.solana.com", json=payload) as resp:
                        data = await resp.json()
                        accounts = data.get("result", {}).get("value", [])
                        for acc in accounts:
                            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            amount = info.get("tokenAmount", {}).get("uiAmount", 0)
                            result["usdc"] = float(amount) if amount else 0
                        
        except Exception as e:
            print(f"Balance error: {e}")
            result["error"] = str(e)
        
        return result
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float) -> dict:
        """Swap USDC to a token"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Solana swap: ${amount_usdc} USDC -> {token_address[:8]}...")
            
            amount_raw = int(amount_usdc * 1e6)
            
            # Try account.trade first
            if hasattr(self.solana_account, 'trade'):
                swap_result = await self.solana_account.trade(
                    from_token=USDC_SOLANA,
                    to_token=token_address,
                    amount=str(amount_raw),
                    slippage_bps=100
                )
                print(f"✅ Swap executed via account.trade: {swap_result}")
                return {"success": True, "result": str(swap_result)}
            
            # Try account.swap
            if hasattr(self.solana_account, 'swap'):
                swap_result = await self.solana_account.swap(
                    from_token=USDC_SOLANA,
                    to_token=token_address,
                    amount=str(amount_raw),
                    slippage_bps=100
                )
                print(f"✅ Swap executed via account.swap: {swap_result}")
                return {"success": True, "result": str(swap_result)}
            
            # List what we can do
            methods = [m for m in dir(self.solana_account) if not m.startswith('_')]
            return {"success": False, "error": f"No trade method. Available: {methods}"}
                
        except Exception as e:
            print(f"❌ Swap error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def swap_token_to_usdc(self, token_address: str, amount_tokens: float = None) -> dict:
        """Swap token back to USDC"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Solana sell: {token_address[:8]}... -> USDC")
            
            # Get token balance
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        self.solana_address,
                        {"mint": token_address},
                        {"encoding": "jsonParsed"}
                    ]
                }
                async with session.post("https://api.mainnet-beta.solana.com", json=payload) as resp:
                    data = await resp.json()
                    accounts = data.get("result", {}).get("value", [])
                    if not accounts:
                        return {"success": False, "error": "No token balance"}
                    
                    info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                    amount_raw = int(info.get("tokenAmount", {}).get("amount", 0))
            
            if amount_raw == 0:
                return {"success": False, "error": "No tokens to sell"}
            
            # Try account.trade first
            if hasattr(self.solana_account, 'trade'):
                swap_result = await self.solana_account.trade(
                    from_token=token_address,
                    to_token=USDC_SOLANA,
                    amount=str(amount_raw),
                    slippage_bps=200
                )
                print(f"✅ Sell executed: {swap_result}")
                return {"success": True, "result": str(swap_result)}
            
            # Try account.swap
            if hasattr(self.solana_account, 'swap'):
                swap_result = await self.solana_account.swap(
                    from_token=token_address,
                    to_token=USDC_SOLANA,
                    amount=str(amount_raw),
                    slippage_bps=200
                )
                print(f"✅ Sell executed: {swap_result}")
                return {"success": True, "result": str(swap_result)}
            
            methods = [m for m in dir(self.solana_account) if not m.startswith('_')]
            return {"success": False, "error": f"No trade method. Available: {methods}"}
                
        except Exception as e:
            print(f"❌ Sell error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

dex_trader = DexTrader()
