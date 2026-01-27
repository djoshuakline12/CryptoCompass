import os
import asyncio
import aiohttp
import base64
from datetime import datetime, timezone

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_QUOTE = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP = "https://quote-api.jup.ag/v6/swap"

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.solana_account = None
        self.initialized = False
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
            
            self.solana_account = await self.cdp.solana.get_or_create_account(name=f"{account_name}-SOL")
            self.solana_address = self.solana_account.address
            print(f"✅ Solana account ready: {self.solana_address}")
            self.chain = "solana"
            
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
                    # SOL balance
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
                    
                    # USDC balance
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
        """Swap USDC to a token via Jupiter + CDP signing"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            print(f"🔄 Solana swap: ${amount_usdc} USDC -> {token_address[:8]}...")
            
            amount_raw = int(amount_usdc * 1e6)  # USDC has 6 decimals
            
            async with aiohttp.ClientSession() as session:
                # Step 1: Get quote from Jupiter
                quote_url = f"{JUPITER_QUOTE}?inputMint={USDC_SOLANA}&outputMint={token_address}&amount={amount_raw}&slippageBps=100"
                print(f"   Getting quote...")
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {"success": False, "error": f"Quote failed: {resp.status} - {error_text}"}
                    quote = await resp.json()
                
                print(f"   Quote received: {quote.get('outAmount', 'N/A')} tokens")
                
                # Step 2: Get swap transaction from Jupiter
                swap_request = {
                    "quoteResponse": quote,
                    "userPublicKey": self.solana_address,
                    "wrapAndUnwrapSol": True,
                    "dynamicComputeUnitLimit": True,
                    "prioritizationFeeLamports": "auto"
                }
                
                print(f"   Building transaction...")
                async with session.post(JUPITER_SWAP, json=swap_request, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {"success": False, "error": f"Swap build failed: {resp.status} - {error_text}"}
                    swap_data = await resp.json()
                
                swap_tx = swap_data.get("swapTransaction")
                if not swap_tx:
                    return {"success": False, "error": "No swap transaction returned"}
                
                print(f"   Signing transaction with CDP...")
                
                # Step 3: Sign with CDP
                signed = await self.solana_account.sign_transaction(swap_tx)
                print(f"   Signed: {type(signed)}")
                
                # Step 4: Send transaction
                print(f"   Sending transaction...")
                result = await self.cdp.solana.send_transaction(
                    signed_transaction=signed.signed_transaction if hasattr(signed, 'signed_transaction') else str(signed),
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
            
            # Get token balance and decimals
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
                        return {"success": False, "error": "No token balance found"}
                    
                    info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                    token_amount = info.get("tokenAmount", {})
                    amount_raw = int(token_amount.get("amount", 0))
                    
                    if amount_raw == 0:
                        return {"success": False, "error": "Zero token balance"}
                
                print(f"   Selling {amount_raw} tokens...")
                
                # Get quote
                quote_url = f"{JUPITER_QUOTE}?inputMint={token_address}&outputMint={USDC_SOLANA}&amount={amount_raw}&slippageBps=200"
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {"success": False, "error": f"Quote failed: {resp.status} - {error_text}"}
                    quote = await resp.json()
                
                print(f"   Quote: ~${int(quote.get('outAmount', 0)) / 1e6:.2f} USDC")
                
                # Get swap transaction
                swap_request = {
                    "quoteResponse": quote,
                    "userPublicKey": self.solana_address,
                    "wrapAndUnwrapSol": True,
                    "dynamicComputeUnitLimit": True,
                    "prioritizationFeeLamports": "auto"
                }
                
                async with session.post(JUPITER_SWAP, json=swap_request, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {"success": False, "error": f"Swap build failed: {resp.status} - {error_text}"}
                    swap_data = await resp.json()
                
                swap_tx = swap_data.get("swapTransaction")
                if not swap_tx:
                    return {"success": False, "error": "No swap transaction"}
                
                # Sign and send
                signed = await self.solana_account.sign_transaction(swap_tx)
                result = await self.cdp.solana.send_transaction(
                    signed_transaction=signed.signed_transaction if hasattr(signed, 'signed_transaction') else str(signed),
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
