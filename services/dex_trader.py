import os
import aiohttp

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_BASE = "https://public.jupiterapi.com"

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.solana_account = None
        self.initialized = False
        self.solana_address = None
        self.wallet_address = None
        self.chain = "solana"
        
    async def initialize(self):
        if self.initialized:
            return True
            
        cdp_key = os.getenv("CDP_API_KEY_NAME", "")
        cdp_secret = os.getenv("CDP_API_KEY_SECRET", "")
        
        if not cdp_key or not cdp_secret:
            print("⚠️  CDP API keys not configured")
            return False
        
        try:
            from cdp import CdpClient
            
            os.environ["CDP_API_KEY_ID"] = cdp_key
            os.environ["CDP_API_KEY_SECRET"] = cdp_secret
            
            self.cdp = CdpClient()
            await self.cdp.__aenter__()
            print("✅ CDP SDK connected")
            
            account_name = os.getenv("CDP_ACCOUNT_NAME", "CryptoCompass")
            
            self.solana_account = await self.cdp.solana.get_or_create_account(name=f"{account_name}-SOL")
            self.solana_address = self.solana_account.address
            self.wallet_address = self.solana_address
            print(f"✅ Solana account ready: {self.solana_address}")
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        result = {"sol": 0, "usdc": 0, "chain": self.chain}
        
        try:
            if self.solana_address:
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
                            result["sol"] = data["result"].get("value", 0) / 1e9
                    
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
            result["error"] = str(e)
        
        return result
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float) -> dict:
        """Swap USDC to a token via Jupiter + CDP signing"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Solana swap: ${amount_usdc} USDC -> {token_address[:8]}...")
            
            amount_raw = int(amount_usdc * 1e6)
            
            async with aiohttp.ClientSession() as session:
                # Get quote WITHOUT platform fee
                quote_url = f"{JUPITER_BASE}/quote?inputMint={USDC_SOLANA}&outputMint={token_address}&amount={amount_raw}&slippageBps=100"
                print(f"   Getting quote...")
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {"success": False, "error": f"Quote failed: {resp.status}"}
                    quote = await resp.json()
                
                # Remove any platform fee from quote if present
                if "platformFee" in quote:
                    del quote["platformFee"]
                
                print(f"   Quote: {quote.get('outAmount', 'N/A')} tokens")
                
                # Build swap with NO fee
                swap_request = {
                    "quoteResponse": quote,
                    "userPublicKey": self.solana_address,
                    "wrapAndUnwrapSol": True,
                    "useSharedAccounts": True,
                    "asLegacyTransaction": False,
                    "useTokenLedger": False,
                    "dynamicComputeUnitLimit": True,
                    "skipUserAccountsRpcCalls": False,
                    "prioritizationFeeLamports": {
                        "priorityLevelWithMaxLamports": {
                            "maxLamports": 1000000,
                            "priorityLevel": "medium"
                        }
                    }
                }
                
                print(f"   Building swap...")
                async with session.post(f"{JUPITER_BASE}/swap", json=swap_request, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"   Swap error: {error_text[:200]}")
                        return {"success": False, "error": f"Swap build failed: {resp.status}"}
                    swap_data = await resp.json()
                
                swap_tx = swap_data.get("swapTransaction")
                if not swap_tx:
                    return {"success": False, "error": "No swap transaction"}
                
                print(f"   Signing...")
                signed = await self.solana_account.sign_transaction(swap_tx)
                
                print(f"   Sending...")
                signed_tx = signed.signed_transaction if hasattr(signed, 'signed_transaction') else str(signed)
                result = await self.cdp.solana.send_transaction(
                    signed_transaction=signed_tx,
                    network="mainnet"
                )
                
                print(f"✅ Swap executed: {result}")
                return {"success": True, "result": str(result)}
                
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
            
            async with aiohttp.ClientSession() as session:
                # Get token balance
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
                    return {"success": False, "error": "Zero balance"}
                
                # Get quote
                quote_url = f"{JUPITER_BASE}/quote?inputMint={token_address}&outputMint={USDC_SOLANA}&amount={amount_raw}&slippageBps=200"
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {"success": False, "error": f"Quote failed: {resp.status}"}
                    quote = await resp.json()
                
                if "platformFee" in quote:
                    del quote["platformFee"]
                
                # Build swap
                swap_request = {
                    "quoteResponse": quote,
                    "userPublicKey": self.solana_address,
                    "wrapAndUnwrapSol": True,
                    "useSharedAccounts": True,
                    "asLegacyTransaction": False,
                    "useTokenLedger": False,
                    "dynamicComputeUnitLimit": True,
                    "skipUserAccountsRpcCalls": False,
                    "prioritizationFeeLamports": {
                        "priorityLevelWithMaxLamports": {
                            "maxLamports": 1000000,
                            "priorityLevel": "medium"
                        }
                    }
                }
                
                async with session.post(f"{JUPITER_BASE}/swap", json=swap_request, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"   Sell error: {error_text[:200]}")
                        return {"success": False, "error": f"Swap build failed"}
                    swap_data = await resp.json()
                
                swap_tx = swap_data.get("swapTransaction")
                if not swap_tx:
                    return {"success": False, "error": "No swap transaction"}
                
                signed = await self.solana_account.sign_transaction(swap_tx)
                signed_tx = signed.signed_transaction if hasattr(signed, 'signed_transaction') else str(signed)
                result = await self.cdp.solana.send_transaction(
                    signed_transaction=signed_tx,
                    network="mainnet"
                )
                
                print(f"✅ Sell executed: {result}")
                return {"success": True, "result": str(result)}
                
        except Exception as e:
            print(f"❌ Sell error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

dex_trader = DexTrader()
