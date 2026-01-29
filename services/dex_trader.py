import os
import json
import asyncio
import aiohttp
import base64
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
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_SECRET", "").replace("\\n", "\n")
            wallet_data = os.getenv("CDP_WALLET_SECRET", "")
            
            print(f"🔍 api_key exists: {bool(api_key)}")
            print(f"🔍 api_secret exists: {bool(api_secret)}")
            print(f"🔍 wallet_data length: {len(wallet_data)}")
            print(f"🔍 wallet_data first 50 chars: {wallet_data[:50]}...")
            
            if not api_key or not api_secret:
                print("❌ Missing CDP API credentials")
                return False
            
            if not wallet_data:
                print("❌ Missing wallet data")
                return False
            
            # Try to parse wallet data - could be JSON, base64, or seed phrase
            data = None
            
            # Try JSON first
            try:
                data = json.loads(wallet_data)
                print(f"🔍 Parsed as JSON, keys: {list(data.keys())}")
            except:
                pass
            
            # Try base64
            if not data:
                try:
                    decoded = base64.b64decode(wallet_data).decode('utf-8')
                    data = json.loads(decoded)
                    print(f"🔍 Parsed as base64 JSON, keys: {list(data.keys())}")
                except:
                    pass
            
            # Maybe it's a seed phrase or private key directly
            if not data:
                if wallet_data.startswith('[') or len(wallet_data.split()) >= 12:
                    print("🔍 Looks like a seed phrase or key array")
                    # For seed phrase, we need the address separately
                    self.solana_address = os.getenv("SOLANA_ADDRESS") or "BQVcTBUUHRcniikRzyfmddzkkUtDABkASvaVua13Yq4n"
                else:
                    print(f"🔍 Unknown format. Starts with: {wallet_data[:20]}")
            
            # Extract address from parsed data
            if data:
                if "default_address" in data:
                    addr = data["default_address"]
                    if isinstance(addr, dict):
                        self.solana_address = addr.get("address_id") or addr.get("address")
                    else:
                        self.solana_address = addr
                elif "address" in data:
                    self.solana_address = data["address"]
                elif "addresses" in data:
                    self.solana_address = data["addresses"][0] if data["addresses"] else None
            
            # Fallback to known address if we can't parse
            if not self.solana_address:
                self.solana_address = os.getenv("SOLANA_ADDRESS", "BQVcTBUUHRcniikRzyfmddzkkUtDABkASvaVua13Yq4n")
                print(f"🔍 Using fallback address: {self.solana_address}")
            
            # Initialize CDP client for potential future signing
            try:
                from cdp import CdpClient
                self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
                print("✅ CDP client initialized")
            except Exception as e:
                print(f"CDP client error: {e}")
            
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
