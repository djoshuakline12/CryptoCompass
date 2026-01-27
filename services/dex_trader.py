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
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        if not self.initialized or not self.account:
            return {"eth": 0, "usdc": 0, "error": "Not initialized"}
        
        result = {"eth": 0, "usdc": 0}
        
        try:
            balances = await self.account.list_balances()
            print(f"Raw balances: {balances}")
            
            for b in balances:
                print(f"  Balance item: {b}, type: {type(b)}")
                if hasattr(b, 'asset'):
                    asset = str(b.asset).lower()
                    amount = float(b.amount) if hasattr(b, 'amount') else 0
                    if 'eth' in asset:
                        result["eth"] = amount
                    elif 'usdc' in asset:
                        result["usdc"] = amount
                elif isinstance(b, dict):
                    asset = str(b.get('asset', '')).lower()
                    amount = float(b.get('amount', 0))
                    if 'eth' in asset:
                        result["eth"] = amount
                    elif 'usdc' in asset:
                        result["usdc"] = amount
                        
        except AttributeError:
            try:
                eth_bal = await self.account.balance(network="base")
                result["eth"] = float(eth_bal) if eth_bal else 0
            except Exception as e2:
                print(f"ETH balance error: {e2}")
                
        except Exception as e:
            print(f"Balance error: {e}")
            result["error"] = str(e)
        
        return result

dex_trader = DexTrader()
