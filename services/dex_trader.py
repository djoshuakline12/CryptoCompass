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
        """Initialize CDP wallet with new SDK"""
        try:
            # Debug: print available env vars (names only, not values)
            cdp_vars = [k for k in os.environ.keys() if 'CDP' in k.upper() or 'WALLET' in k.upper() or 'SOLANA' in k.upper()]
            print(f"🔍 Available env vars: {cdp_vars}")
            
            # Try multiple possible env var names
            api_key = os.getenv("CDP_API_KEY_NAME") or os.getenv("CDP_API_KEY") or os.getenv("COINBASE_API_KEY")
            api_secret = (os.getenv("CDP_API_KEY_PRIVATE_KEY") or os.getenv("CDP_PRIVATE_KEY") or os.getenv("COINBASE_PRIVATE_KEY") or "").replace("\\n", "\n")
            wallet_data = os.getenv("CDP_WALLET_DATA") or os.getenv("WALLET_DATA")
            
            print(f"🔍 api_key exists: {bool(api_key)}")
            print(f"🔍 api_secret exists: {bool(api_secret)}")
            print(f"🔍 wallet_data exists: {bool(wallet_data)}")
            
            if not api_key or not api_secret:
                print("❌ Missing CDP API credentials")
                # Try to continue with just wallet address for read-only mode
                if wallet_data:
                    try:
                        data = json.loads(wallet_data)
                        print(f"🔍 wallet_data keys: {list(data.keys())}")
                        
                        # Extract address from various possible formats
                        if "default_address" in data:
                            addr = data["default_address"]
                            if isinstance(addr, dict):
                                self.solana_address = addr.get("address_id") or addr.get("address")
                            else:
                                self.solana_address = addr
                        elif "address" in data:
                            self.solana_address = data["address"]
                        elif "wallet_id" in data:
                            # Old format - need to find address differently
                            print(f"🔍 Old wallet format detected")
                        
                        if self.solana_address:
                            print(f"✅ Read-only mode: {self.solana_address}")
                            self.initialized = True
                            return True
                    except Exception as e:
                        print(f"Wallet parse error: {e}")
                
                return False
            
            # Full initialization with signing capability
            from cdp import CdpClient
            
            self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
            
            if wallet_data:
                data = json.loads(wallet_data)
                print(f"🔍 wallet_data keys: {list(data.keys())}")
                
                # Try to get address
                if "default_address" in data:
                    addr = data["default_address"]
                    if isinstance(addr, dict):
                        self.solana_address = addr.get("address_id") or addr.get("address")
                    else:
                        self.solana_address = addr
                elif "address" in data:
                    self.solana_address = data["address"]
                
                # Try to import account for signing
                try:
                    from cdp.solana_account import SolanaAccount
                    # Check what import methods are available
                    print(f"🔍 SolanaAccount methods: {[m for m in dir(SolanaAccount) if not m.startswith('_')]}")
                except Exception as e:
                    print(f"SolanaAccount import error: {e}")
            
            if self.solana_address:
                self.initialized = True
                print(f"✅ Solana account ready: {self.solana_address}")
                return True
            
            print("❌ Could not determine Solana address")
            return False
            
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
        result = {"success": False, "tx_hash": "", "error": "Read-only mode - signing not available"}
        return result
    
    async def swap_token_to_usdc(self, token_address: str, max_retries: int = 3) -> dict:
        result = {"success": False, "tx_hash": "", "error": "Read-only mode - signing not available"}
        return result

dex_trader = DexTrader()
