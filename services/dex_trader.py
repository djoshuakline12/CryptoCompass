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
            from cdp import CdpClient
            from cdp.solana_account import SolanaAccount
            
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_PRIVATE_KEY", "").replace("\\n", "\n")
            wallet_data = os.getenv("CDP_WALLET_DATA")
            
            if not all([api_key, api_secret]):
                print("❌ Missing CDP credentials")
                return False
            
            # Initialize client
            self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
            
            # Try to import existing wallet or use address directly
            if wallet_data:
                try:
                    data = json.loads(wallet_data)
                    # New SDK might have different import method
                    if "address" in data:
                        self.solana_address = data["address"]
                    elif "default_address" in data:
                        self.solana_address = data["default_address"]
                    elif "addresses" in data and len(data["addresses"]) > 0:
                        self.solana_address = data["addresses"][0]
                    
                    # Try to import the account
                    if "private_key" in data or "seed" in data:
                        # Import from private key/seed
                        self.solana_account = SolanaAccount.import_account(data)
                        self.solana_address = self.solana_account.address
                except Exception as e:
                    print(f"Wallet import error: {e}")
            
            # If we have an address from env, use it directly
            if not self.solana_address:
                # Check if address is stored separately
                self.solana_address = os.getenv("SOLANA_WALLET_ADDRESS", "")
            
            if self.solana_address:
                self.initialized = True
                print(f"✅ Solana account ready: {self.solana_address}")
                return True
            else:
                print("❌ No Solana address found")
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
        """Swap USDC to token"""
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized or not self.solana_account:
            result["error"] = "DEX not initialized or no signing capability"
            return result
        
        trade_key = f"buy_{token_address}"
        if trade_key in self.pending_trades:
            result["error"] = "Trade already pending"
            return result
        
        if self.last_trade_time:
            elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
            if elapsed < self.min_trade_interval:
                await asyncio.sleep(self.min_trade_interval - elapsed)
        
        self.pending_trades.add(trade_key)
        
        try:
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        amount_raw = int(amount_usdc * 1e6)
                        quote_url = f"https://public.jupiterapi.com/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={amount_raw}&slippageBps=200"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Quote failed: {resp.status}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No route found"
                            continue
                        
                        swap_url = "https://public.jupiterapi.com/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote,
                            "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": 2000000
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Swap build failed: {resp.status}"
                                continue
                            swap_data = await resp.json()
                        
                        if not swap_data.get("swapTransaction"):
                            result["error"] = "No transaction returned"
                            continue
                        
                        tx_base64 = swap_data["swapTransaction"]
                        
                        # Sign with new SDK
                        try:
                            signed = self.solana_account.sign_transaction(tx_base64)
                        except AttributeError:
                            # Try alternate method
                            signed = await self.solana_account.sign(tx_base64)
                        
                        send_body = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "sendTransaction",
                            "params": [signed, {"skipPreflight": True, "maxRetries": 3}]
                        }
                        
                        rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
                        async with session.post(rpc_url, json=send_body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            send_result = await resp.json()
                        
                        if "error" in send_result:
                            error_msg = str(send_result["error"])
                            if "blockhash" in error_msg.lower():
                                await asyncio.sleep(1)
                                continue
                            result["error"] = error_msg[:100]
                            continue
                        
                        result["success"] = True
                        result["tx_hash"] = send_result.get("result", "")
                        self.last_trade_time = datetime.now(timezone.utc)
                        break
                        
                except asyncio.TimeoutError:
                    result["error"] = f"Timeout on attempt {attempt + 1}"
                    await asyncio.sleep(2)
                except Exception as e:
                    result["error"] = str(e)[:100]
                    await asyncio.sleep(2)
        finally:
            self.pending_trades.discard(trade_key)
        
        return result
    
    async def swap_token_to_usdc(self, token_address: str, max_retries: int = 3) -> dict:
        """Swap ALL of a token to USDC"""
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized or not self.solana_account:
            result["error"] = "DEX not initialized or no signing capability"
            return result
        
        trade_key = f"sell_{token_address}"
        if trade_key in self.pending_trades:
            result["error"] = "Sell already pending"
            return result
        
        self.pending_trades.add(trade_key)
        
        try:
            token_balance = 0
            
            async with aiohttp.ClientSession() as session:
                helius_key = os.getenv('HELIUS_API_KEY', '')
                url = f"https://api.helius.xyz/v0/addresses/{self.solana_address}/balances?api-key={helius_key}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for token in data.get("tokens", []):
                            if token.get("mint") == token_address:
                                token_balance = int(token.get("amount", 0))
                                break
            
            if token_balance == 0:
                result["error"] = "No token balance"
                return result
            
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        quote_url = f"https://public.jupiterapi.com/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount={token_balance}&slippageBps=300"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                if "route" in error_text.lower():
                                    result["error"] = "No liquidity to sell"
                                    return result
                                result["error"] = f"Quote failed: {resp.status}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No sell route"
                            return result
                        
                        swap_url = "https://public.jupiterapi.com/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote,
                            "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": 2000000
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Swap build failed: {resp.status}"
                                continue
                            swap_data = await resp.json()
                        
                        if not swap_data.get("swapTransaction"):
                            result["error"] = "No transaction"
                            continue
                        
                        tx_base64 = swap_data["swapTransaction"]
                        
                        try:
                            signed = self.solana_account.sign_transaction(tx_base64)
                        except AttributeError:
                            signed = await self.solana_account.sign(tx_base64)
                        
                        send_body = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "sendTransaction",
                            "params": [signed, {"skipPreflight": True, "maxRetries": 3}]
                        }
                        
                        rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
                        async with session.post(rpc_url, json=send_body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            send_result = await resp.json()
                        
                        if "error" in send_result:
                            error_msg = str(send_result["error"])
                            if "blockhash" in error_msg.lower():
                                await asyncio.sleep(1)
                                continue
                            result["error"] = error_msg[:100]
                            continue
                        
                        result["success"] = True
                        result["tx_hash"] = send_result.get("result", "")
                        self.last_trade_time = datetime.now(timezone.utc)
                        break
                        
                except asyncio.TimeoutError:
                    result["error"] = f"Timeout attempt {attempt + 1}"
                    await asyncio.sleep(2)
                except Exception as e:
                    result["error"] = str(e)[:100]
                    await asyncio.sleep(2)
        finally:
            self.pending_trades.discard(trade_key)
        
        return result

dex_trader = DexTrader()
