import os
import asyncio
from datetime import datetime, timezone
from config import settings

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.wallet = None
        self.account = None
        self.initialized = False
        
    async def initialize(self):
        if self.initialized:
            return True
            
        cdp_key = os.getenv("CDP_API_KEY_NAME", "")
        cdp_secret = os.getenv("CDP_API_KEY_SECRET", "")
        
        if not cdp_key or not cdp_secret:
            print("⚠️  CDP API keys not configured - paper trading only")
            return False
        
        try:
            from cdp import Cdp, Wallet
            
            Cdp.configure(cdp_key, cdp_secret)
            print("✅ CDP SDK configured")
            
            wallet_id = os.getenv("CDP_WALLET_ID", "")
            wallet_seed = os.getenv("CDP_WALLET_SEED", "")
            
            if wallet_id and wallet_seed:
                self.wallet = Wallet.import_data({
                    "wallet_id": wallet_id,
                    "seed": wallet_seed,
                    "network_id": "base-mainnet"
                })
                print(f"✅ Loaded existing wallet: {wallet_id}")
            else:
                self.wallet = Wallet.create(network_id="base-mainnet")
                data = self.wallet.export_data()
                print(f"✅ Created new CDP wallet on Base")
                print(f"   Wallet ID: {data['wallet_id']}")
                print(f"   Address: {self.wallet.default_address.address_id}")
                print(f"   ⚠️  SAVE THESE TO RAILWAY ENV VARS:")
                print(f"   CDP_WALLET_ID={data['wallet_id']}")
                print(f"   CDP_WALLET_SEED={data['seed']}")
            
            self.account = self.wallet.default_address
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            return False
    
    async def get_balance(self, token: str = "USDC") -> float:
        if not self.initialized:
            return 0
        try:
            balances = self.wallet.balances()
            for asset, amount in balances.items():
                if token.upper() in str(asset).upper():
                    return float(amount)
            return 0
        except:
            return 0

dex_trader = DexTrader()
