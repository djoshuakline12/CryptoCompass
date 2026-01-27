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
    
    async def get_eth_balance(self) -> float:
        if not self.initialized or not self.account:
            return 0
        try:
            balance = await self.account.balance()
            return float(balance) if balance else 0
        except Exception as e:
            print(f"ETH balance error: {e}")
            return 0
    
    async def get_usdc_balance(self) -> float:
        if not self.initialized or not self.account:
            return 0
        try:
            balance = await self.account.balance(token="usdc")
            return float(balance) if balance else 0
        except Exception as e:
            print(f"USDC balance error: {e}")
            return 0

dex_trader = DexTrader()
