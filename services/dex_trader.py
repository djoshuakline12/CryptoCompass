import os
import aiohttp

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUPITER_BASE = "https://public.jupiterapi.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

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
                    async with session.post(SOLANA_RPC, json=payload) as resp:
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
                    async with session.post(SOLANA_RPC, json=payload) as resp:
                        data = await resp.json()
                        accounts = data.get("result", {}).get("value", [])
                        for acc in accounts:
                            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            amount = info.get("tokenAmount", {}).get("uiAmount", 0)
                            result["usdc"] = float(amount) if amount else 0
                        
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    async def _execute_swap(self, session, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 100) -> dict:
        """Execute a swap with retry logic for blockhash issues"""
        
        for attempt in range(3):  # Retry up to 3 times
            try:
                # Get fresh quote
                quote_url = f"{JUPITER_BASE}/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_raw}&slippageBps={slippage_bps}"
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return {"success": False, "error": f"Quote failed: {resp.status}"}
                    quote = await resp.json()
                
                if "platformFee" in quote:
                    del quote["platformFee"]
                
                # Build swap - try without shared accounts first
                for use_shared in [False, True]:
                    swap_request = {
                        "quoteResponse": quote,
                        "userPublicKey": self.solana_address,
                        "wrapAndUnwrapSol": True,
                        "useSharedAccounts": use_shared,
                        "dynamicComputeUnitLimit": True,
                        "prioritizationFeeLamports": {
                            "priorityLevelWithMaxLamports": {
                                "maxLamports": 2000000,
                                "priorityLevel": "veryHigh"
                            }
                        }
                    }
                    
                    async with session.post(f"{JUPITER_BASE}/swap", json=swap_request, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            swap_data = await resp.json()
                            break
                        elif use_shared:
                            error_text = await resp.text()
                            return {"success": False, "error": f"Swap build failed: {error_text[:100]}"}
                
                swap_tx = swap_data.get("swapTransaction")
                if not swap_tx:
                    return {"success": False, "error": "No swap transaction"}
                
                # Sign immediately
                signed = await self.solana_account.sign_transaction(swap_tx)
                
                if hasattr(signed, 'signed_transaction'):
                    signed_tx = signed.signed_transaction
                elif hasattr(signed, 'transaction'):
                    signed_tx = signed.transaction
                else:
                    signed_tx = str(signed)
                
                # Send with skipPreflight to avoid simulation delays
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        signed_tx, 
                        {
                            "encoding": "base64",
                            "skipPreflight": True,
                            "preflightCommitment": "processed",
                            "maxRetries": 3
                        }
                    ]
                }
                
                async with session.post(SOLANA_RPC, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as rpc_resp:
                    rpc_data = await rpc_resp.json()
                    
                    if "error" in rpc_data:
                        error = rpc_data["error"]
                        error_msg = error.get("message", str(error))
                        
                        # Retry on blockhash errors
                        if "Blockhash not found" in error_msg or "BlockhashNotFound" in str(error):
                            print(f"   Blockhash expired, retrying ({attempt + 1}/3)...")
                            continue
                        
                        return {"success": False, "error": error_msg}
                    
                    return {"success": True, "result": rpc_data.get("result")}
                    
            except Exception as e:
                if attempt < 2:
                    print(f"   Error, retrying ({attempt + 1}/3): {e}")
                    continue
                return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float) -> dict:
        """Swap USDC to a token"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        print(f"🔄 Solana swap: ${amount_usdc} USDC -> {token_address[:8]}...")
        amount_raw = int(amount_usdc * 1e6)
        
        async with aiohttp.ClientSession() as session:
            result = await self._execute_swap(session, USDC_SOLANA, token_address, amount_raw, slippage_bps=100)
            
            if result["success"]:
                print(f"✅ Swap executed: {result['result']}")
            else:
                print(f"❌ Swap failed: {result['error']}")
            
            return result
    
    async def swap_token_to_usdc(self, token_address: str, amount_tokens: float = None) -> dict:
        """Swap token back to USDC"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
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
            async with session.post(SOLANA_RPC, json=payload) as resp:
                data = await resp.json()
                accounts = data.get("result", {}).get("value", [])
                if not accounts:
                    return {"success": False, "error": "No token balance"}
                
                info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                amount_raw = int(info.get("tokenAmount", {}).get("amount", 0))
            
            if amount_raw == 0:
                return {"success": False, "error": "Zero balance"}
            
            print(f"   Selling {amount_raw} tokens...")
            
            result = await self._execute_swap(session, token_address, USDC_SOLANA, amount_raw, slippage_bps=300)
            
            if result["success"]:
                print(f"✅ Sell executed: {result['result']}")
            else:
                print(f"❌ Sell failed: {result['error']}")
            
            return result

dex_trader = DexTrader()
