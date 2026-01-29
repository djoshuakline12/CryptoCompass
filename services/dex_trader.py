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
        self.solana_account = None
        self.solana_address = "BQVcTBUUHRcniikRzyfmddzkkUtDABkASvaVua13Yq4n"
        self.chain = "solana"
        self.last_trade_time = None
        self.min_trade_interval = 5
        self.pending_trades = set()
    
    async def initialize(self):
        """Initialize CDP wallet"""
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
            
            try:
                self.solana_account = self.solana_client.get_account(address=self.solana_address)
                print(f"✅ Got Solana account: {self.solana_address}")
                print(f"🔍 Account methods: {[x for x in dir(self.solana_account) if not x.startswith('_')][:10]}")
            except Exception as e:
                print(f"⚠️ Account error: {e}")
            
            self.initialized = True
            print(f"✅ Solana ready: {self.solana_address}")
            return True
            
        except Exception as e:
            print(f"❌ CDP init failed: {e}")
            return False
    
    async def get_balances(self) -> dict:
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
        """Swap USDC to token using Jupiter"""
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized:
            result["error"] = "DEX not initialized"
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
                        # Get Jupiter quote
                        amount_raw = int(amount_usdc * 1e6)
                        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={amount_raw}&slippageBps=300"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                result["error"] = f"Quote failed: {error_text[:100]}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No route found"
                            continue
                        
                        print(f"🔍 Quote OK: {amount_usdc} USDC -> {quote.get('outAmount')} tokens")
                        
                        # Build swap transaction
                        swap_url = "https://quote-api.jup.ag/v6/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote,
                            "wrapAndUnwrapSol": True,
                            "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": "auto"
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                print(f"🔍 Swap build error: {error_text}")
                                result["error"] = f"Swap build: {error_text[:100]}"
                                continue
                            swap_data = await resp.json()
                        
                        if not swap_data.get("swapTransaction"):
                            result["error"] = "No transaction returned"
                            continue
                        
                        tx_base64 = swap_data["swapTransaction"]
                        print(f"🔍 Got swap transaction, sending via CDP...")
                        
                        # Send via CDP SDK
                        try:
                            tx_result = self.solana_client.send_transaction(
                                address=self.solana_address,
                                transaction=tx_base64
                            )
                            print(f"🔍 TX result type: {type(tx_result)}")
                            print(f"🔍 TX result: {tx_result}")
                            
                            # Handle async result
                            if asyncio.iscoroutine(tx_result):
                                tx_result = await tx_result
                            
                            if hasattr(tx_result, 'signature'):
                                result["success"] = True
                                result["tx_hash"] = tx_result.signature
                            elif hasattr(tx_result, 'transaction_hash'):
                                result["success"] = True
                                result["tx_hash"] = tx_result.transaction_hash
                            elif isinstance(tx_result, dict):
                                result["success"] = True
                                result["tx_hash"] = tx_result.get("signature", str(tx_result))
                            else:
                                result["success"] = True
                                result["tx_hash"] = str(tx_result)
                            
                            self.last_trade_time = datetime.now(timezone.utc)
                            print(f"✅ Transaction sent: {result['tx_hash']}")
                            return result
                            
                        except Exception as e:
                            error_str = str(e)
                            print(f"❌ CDP send error: {error_str}")
                            if "blockhash" in error_str.lower():
                                await asyncio.sleep(1)
                                continue
                            result["error"] = f"Send failed: {error_str[:80]}"
                            continue
                        
                except asyncio.TimeoutError:
                    result["error"] = f"Timeout attempt {attempt + 1}"
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"❌ Swap error: {e}")
                    result["error"] = str(e)[:100]
                    await asyncio.sleep(2)
                    
        finally:
            self.pending_trades.discard(trade_key)
        
        return result
    
    async def swap_token_to_usdc(self, token_address: str, max_retries: int = 3) -> dict:
        """Swap ALL of a token to USDC"""
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
            # Get token balance
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
                        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount={token_balance}&slippageBps=500"
                        
                        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                if "route" in error_text.lower():
                                    result["error"] = "No liquidity to sell"
                                    return result
                                result["error"] = f"Quote failed: {error_text[:100]}"
                                continue
                            quote = await resp.json()
                        
                        if not quote.get("outAmount"):
                            result["error"] = "No sell route"
                            return result
                        
                        swap_url = "https://quote-api.jup.ag/v6/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote,
                            "wrapAndUnwrapSol": True,
                            "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": "auto"
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                result["error"] = f"Swap build: {error_text[:100]}"
                                continue
                            swap_data = await resp.json()
                        
                        if not swap_data.get("swapTransaction"):
                            result["error"] = "No transaction"
                            continue
                        
                        tx_base64 = swap_data["swapTransaction"]
                        
                        try:
                            tx_result = self.solana_client.send_transaction(
                                address=self.solana_address,
                                transaction=tx_base64
                            )
                            
                            if asyncio.iscoroutine(tx_result):
                                tx_result = await tx_result
                            
                            if hasattr(tx_result, 'signature'):
                                result["success"] = True
                                result["tx_hash"] = tx_result.signature
                            elif hasattr(tx_result, 'transaction_hash'):
                                result["success"] = True
                                result["tx_hash"] = tx_result.transaction_hash
                            else:
                                result["success"] = True
                                result["tx_hash"] = str(tx_result)
                            
                            self.last_trade_time = datetime.now(timezone.utc)
                            return result
                            
                        except Exception as e:
                            error_str = str(e)
                            print(f"❌ CDP send error: {error_str}")
                            if "blockhash" in error_str.lower():
                                await asyncio.sleep(1)
                                continue
                            result["error"] = f"Send failed: {error_str[:80]}"
                            continue
                        
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
