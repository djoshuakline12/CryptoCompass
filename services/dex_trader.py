import os
import json
import asyncio
import aiohttp
from datetime import datetime, timezone

class DexTrader:
    def __init__(self):
        self.initialized = False
        self.client = None
        self.solana_account = None
        self.solana_address = None
        self.chain = "solana"
        self.last_trade_time = None
        self.min_trade_interval = 5
        self.pending_trades = set()
    
    async def initialize(self):
        """Initialize CDP wallet"""
        try:
            # Use correct env var names
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_SECRET", "").replace("\\n", "\n")
            wallet_data = os.getenv("CDP_WALLET_SECRET")
            
            print(f"🔍 api_key exists: {bool(api_key)}")
            print(f"🔍 api_secret exists: {bool(api_secret)}")
            print(f"🔍 wallet_data exists: {bool(wallet_data)}")
            
            if not api_key or not api_secret:
                print("❌ Missing CDP API credentials")
                return False
            
            if not wallet_data:
                print("❌ Missing wallet data")
                return False
            
            # Parse wallet data
            data = json.loads(wallet_data)
            print(f"🔍 wallet_data keys: {list(data.keys())}")
            
            # Extract address from wallet data
            if "default_address" in data:
                addr = data["default_address"]
                if isinstance(addr, dict):
                    self.solana_address = addr.get("address_id") or addr.get("address")
                else:
                    self.solana_address = addr
            elif "address" in data:
                self.solana_address = data["address"]
            
            if not self.solana_address:
                print(f"❌ Could not find address in wallet data. Keys: {list(data.keys())}")
                # Print more details to debug
                for k, v in data.items():
                    if isinstance(v, dict):
                        print(f"🔍 {k}: {list(v.keys())}")
                    else:
                        print(f"🔍 {k}: {type(v).__name__}")
                return False
            
            # Initialize CDP client
            from cdp import CdpClient
            self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
            
            # Try to get signing capability
            try:
                # Check what's available for Solana
                from cdp import solana_account
                print(f"🔍 solana_account contents: {[x for x in dir(solana_account) if not x.startswith('_')]}")
            except Exception as e:
                print(f"solana_account import: {e}")
            
            self.initialized = True
            print(f"✅ Solana account ready: {self.solana_address}")
            return True
            
        except Exception as e:
            print(f"❌ CDP init failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        """Get current wallet balances"""
        balances = {"sol": 0, "usdc": 0}
        
        if not self.solana_address:
            return balances
        
        try:
            helius_key = os.getenv('HELIUS_API_KEY', '')
            if not helius_key:
                return balances
                
            async with aiohttp.ClientSession() as session:
                url = f"https://api.helius.xyz/v0/addresses/{self.solana_address}/balances?api-key={helius_key}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        balances["sol"] = data.get("nativeBalance", 0) / 1e9
                        
                        for token in data.get("tokens", []):
                            if token.get("mint") == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                                balances["usdc"] = float(token.get("amount", 0)) / 1e6
                                break
        except Exception as e:
            print(f"Balance check error: {e}")
        
        return balances
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float, max_retries: int = 3) -> dict:
        result = {"success": False, "tx_hash": "", "error": "Signing not yet implemented for new SDK"}
        return result
    
    async def swap_token_to_usdc(self, token_address: str, max_retries: int = 3) -> dict:
        result = {"success": False, "tx_hash": "", "error": "Signing not yet implemented for new SDK"}
        return result

dex_trader = DexTrader()
