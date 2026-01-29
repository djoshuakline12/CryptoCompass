import os
import json
import asyncio
import aiohttp
from datetime import datetime, timezone

class DexTrader:
    def __init__(self):
        self.initialized = False
        self.client = None
        self.solana_client = None
        self.solana_address = "BQVcTBUUHRcniikRzyfmddzkkUtDABkASvaVua13Yq4n"
        self.chain = "solana"
        self.last_trade_time = None
        self.min_trade_interval = 5
        self.pending_trades = set()
    
    async def initialize(self):
        try:
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_SECRET", "").replace("\\n", "\n")
            
            if not api_key or not api_secret:
                print("❌ Missing CDP API credentials")
                return False
            
            from cdp import CdpClient
            from cdp.solana_client import SolanaClient
            
            self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
            self.solana_client = SolanaClient(self.client.api_clients)
            
            # Debug: check send_transaction signature
            import inspect
            try:
                sig = inspect.signature(self.solana_client.send_transaction)
                print(f"🔍 send_transaction params: {list(sig.parameters.keys())}")
            except Exception as e:
                print(f"🔍 Could not inspect: {e}")
            
            self.initialized = True
            print(f"✅ Solana ready: {self.solana_address}")
            return True
            
        except Exception as e:
            print(f"❌ CDP init failed: {e}")
            return False
    
    async def get_balances(self) -> dict:
        balances = {"sol": 0, "usdc": 0}
        try:
            helius_key = os.getenv('HELIUS_API_KEY', '')
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
            print(f"Balance error: {e}")
        return balances
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float, max_retries: int = 3) -> dict:
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized:
            result["error"] = "DEX not initialized"
            return result
        
        trade_key = f"buy_{token_address}"
        if trade_key in self.pending_trades:
            result["error"] = "Trade already pending"
            return result
        
        self.pending_trades.add(trade_key)
        
        try:
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        amount_raw = int(amount_usdc * 1e6)
                        quote_url = f"https://public.jupiterapi.com/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={amount_raw}&slippageBps=300"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Quote failed: {resp.status}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No route found"
                            continue
                        
                        if "platformFee" in quote:
                            del quote["platformFee"]
                        
                        print(f"🔍 Quote: {amount_usdc} USDC -> {int(quote.get('outAmount', 0))} tokens")
                        
                        swap_url = "https://public.jupiterapi.com/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            resp_text = await resp.text()
                            if resp.status != 200:
                                print(f"🔍 Swap error: {resp_text[:200]}")
                                result["error"] = f"Swap: {resp_text[:80]}"
                                continue
                            swap_data = json.loads(resp_text)
                        
                        tx_base64 = swap_data.get("swapTransaction")
                        if not tx_base64:
                            result["error"] = "No transaction"
                            continue
                        
                        print(f"🔍 Sending via CDP...")
                        
                        try:
                            # Try different method signatures
                            tx_result = None
                            
                            # Try 1: Just transaction
                            try:
                                tx_result = self.solana_client.send_transaction(tx_base64)
                            except TypeError:
                                pass
                            
                            # Try 2: transaction as keyword
                            if tx_result is None:
                                try:
                                    tx_result = self.solana_client.send_transaction(transaction=tx_base64)
                                except TypeError:
                                    pass
                            
                            # Try 3: With address as positional
                            if tx_result is None:
                                try:
                                    tx_result = self.solana_client.send_transaction(self.solana_address, tx_base64)
                                except TypeError:
                                    pass
                            
                            if tx_result is None:
                                result["error"] = "Could not call send_transaction"
                                continue
                            
                            if asyncio.iscoroutine(tx_result):
                                tx_result = await tx_result
                            
                            print(f"🔍 TX result: {tx_result}")
                            
                            result["success"] = True
                            if hasattr(tx_result, 'signature'):
                                result["tx_hash"] = tx_result.signature
                            elif isinstance(tx_result, dict):
                                result["tx_hash"] = tx_result.get("signature", str(tx_result))
                            else:
                                result["tx_hash"] = str(tx_result)
                            
                            self.last_trade_time = datetime.now(timezone.utc)
                            print(f"✅ TX sent: {result['tx_hash'][:30]}...")
                            return result
                            
                        except Exception as e:
                            print(f"❌ CDP error: {e}")
                            result["error"] = str(e)[:100]
                        
                except asyncio.TimeoutError:
                    result["error"] = f"Timeout {attempt + 1}"
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"❌ Error: {e}")
                    result["error"] = str(e)[:100]
                    await asyncio.sleep(2)
                    
        finally:
            self.pending_trades.discard(trade_key)
        
        return result
    
    async def swap_token_to_usdc(self, token_address: str, max_retries: int = 3) -> dict:
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized:
            result["error"] = "DEX not initialized"
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
                        quote_url = f"https://public.jupiterapi.com/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount={token_balance}&slippageBps=500"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Quote failed: {resp.status}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No sell route"
                            return result
                        
                        if "platformFee" in quote:
                            del quote["platformFee"]
                        
                        swap_url = "https://public.jupiterapi.com/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Swap: {resp.status}"
                                continue
                            swap_data = await resp.json()
                        
                        tx_base64 = swap_data.get("swapTransaction")
                        if not tx_base64:
                            result["error"] = "No transaction"
                            continue
                        
                        try:
                            tx_result = None
                            try:
                                tx_result = self.solana_client.send_transaction(tx_base64)
                            except TypeError:
                                try:
                                    tx_result = self.solana_client.send_transaction(transaction=tx_base64)
                                except TypeError:
                                    tx_result = self.solana_client.send_transaction(self.solana_address, tx_base64)
                            
                            if asyncio.iscoroutine(tx_result):
                                tx_result = await tx_result
                            
                            result["success"] = True
                            if hasattr(tx_result, 'signature'):
                                result["tx_hash"] = tx_result.signature
                            else:
                                result["tx_hash"] = str(tx_result)
                            
                            self.last_trade_time = datetime.now(timezone.utc)
                            return result
                            
                        except Exception as e:
                            result["error"] = str(e)[:100]
                        
                except asyncio.TimeoutError:
                    result["error"] = f"Timeout {attempt + 1}"
                    await asyncio.sleep(2)
                except Exception as e:
                    result["error"] = str(e)[:100]
                    await asyncio.sleep(2)
                    
        finally:
            self.pending_trades.discard(trade_key)
        
        return result

dex_trader = DexTrader()
