import os
import asyncio
from datetime import datetime, timezone
from config import settings

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
            print(f"   Fund this address with ETH and USDC to enable live trading")
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balance(self, token: str = "ETH") -> float:
        if not self.initialized or not self.account:
            return 0
        try:
            if token.upper() == "ETH":
                balance = await self.account.balance()
                return float(balance) if balance else 0
            return 0
        except Exception as e:
            print(f"Balance error: {e}")
            return 0
    
    async def swap(self, from_token: str, to_token: str, amount: float) -> dict:
        if not self.initialized:
            return {"success": False, "error": "Not initialized"}
        
        try:
            result = await self.account.swap(
                from_token=from_token,
                to_token=to_token,
                from_amount=str(int(amount * 1e18)),
                slippage_bps=100
            )
            
            print(f"✅ Swap complete: {result}")
            return {"success": True, "result": str(result)}
            
        except Exception as e:
            print(f"❌ Swap error: {e}")
            return {"success": False, "error": str(e)}

dex_trader = DexTrader()
