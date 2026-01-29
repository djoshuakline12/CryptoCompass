import os
import json
import asyncio
import aiohttp
from datetime import datetime, timezone

class DexTrader:
    def __init__(self):
        self.initialized = False
        self.wallet = None
        self.solana_address = None
        self.chain = "solana"
        self.last_trade_time = None
        self.min_trade_interval = 5  # Seconds between trades
        
        # Track pending trades to prevent duplicates
        self.pending_trades = set()
    
    async def initialize(self):
        """Initialize CDP wallet"""
        try:
            from cdp import Cdp, Wallet
            
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_PRIVATE_KEY", "").replace("\\n", "\n")
            wallet_data = os.getenv("CDP_WALLET_DATA")
            
            if not all([api_key, api_secret, wallet_data]):
                print("❌ Missing CDP credentials")
                return False
            
            Cdp.configure(api_key, api_secret)
            
            data = json.loads(wallet_data)
            self.wallet = Wallet.import_data(data)
            self.solana_address = self.wallet.default_address.address_id
            self.initialized = True
            print(f"✅ Solana account ready: {self.solana_address}")
            return True
            
        except Exception as e:
            print(f"❌ CDP init failed: {e}")
            return False
    
    async def get_balances(self) -> dict:
        """Get current wallet balances"""
        balances = {"sol": 0, "usdc": 0}
        
        if not self.initialized:
            return balances
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.helius.xyz/v0/addresses/{self.solana_address}/balances?api-key={os.getenv('HELIUS_API_KEY', '')}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Native SOL
                        balances["sol"] = data.get("nativeBalance", 0) / 1e9
                        
                        # Find USDC
                        for token in data.get("tokens", []):
                            if token.get("mint") == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                                balances["usdc"] = float(token.get("amount", 0)) / 1e6
                                break
        except Exception as e:
            print(f"Balance check error: {e}")
        
        return balances
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float, max_retries: int = 3) -> dict:
        """
        Swap USDC to token with retry logic and duplicate prevention
        """
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized:
            result["error"] = "DEX not initialized"
            return result
        
        # Prevent duplicate trades
        trade_key = f"buy_{token_address}"
        if trade_key in self.pending_trades:
            result["error"] = "Trade already pending"
            return result
        
        # Rate limit
        if self.last_trade_time:
            elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
            if elapsed < self.min_trade_interval:
                await asyncio.sleep(self.min_trade_interval - elapsed)
        
        self.pending_trades.add(trade_key)
        
        try:
            for attempt in range(max_retries):
                try:
                    # Get fresh quote
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
                        
                        # Build transaction
                        swap_url = "https://public.jupiterapi.com/swap"
                        swap_body = {
                            "userPublicKey": self.solana_address,
                            "quoteResponse": quote,
                            "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": 2000000  # 0.002 SOL priority
                        }
                        
                        async with session.post(swap_url, json=swap_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                result["error"] = f"Swap build failed: {resp.status}"
                                continue
                            swap_data = await resp.json()
                        
                        if not swap_data.get("swapTransaction"):
                            result["error"] = "No transaction returned"
                            continue
                        
                        # Sign and send
                        tx_base64 = swap_data["swapTransaction"]
                        
                        signed = self.wallet.default_address.sign_transaction(tx_base64)
                        
                        # Send with skipPreflight for speed
                        send_body = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "sendTransaction",
                            "params": [
                                signed,
                                {"skipPreflight": True, "maxRetries": 3}
                            ]
                        }
                        
                        rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
                        async with session.post(rpc_url, json=send_body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            send_result = await resp.json()
                        
                        if "error" in send_result:
                            error_msg = str(send_result["error"])
                            if "blockhash" in error_msg.lower():
                                print(f"Blockhash expired, retry {attempt + 1}")
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
        """
        Swap ALL of a token to USDC with retry logic
        """
        result = {"success": False, "tx_hash": "", "error": ""}
        
        if not self.initialized:
            result["error"] = "DEX not initialized"
            return result
        
        # Prevent duplicate sells
        trade_key = f"sell_{token_address}"
        if trade_key in self.pending_trades:
            result["error"] = "Sell already pending"
            return result
        
        self.pending_trades.add(trade_key)
        
        try:
            # Get token balance
            token_balance = 0
            decimals = 9
            
            async with aiohttp.ClientSession() as session:
                url = f"https://api.helius.xyz/v0/addresses/{self.solana_address}/balances?api-key={os.getenv('HELIUS_API_KEY', '')}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for token in data.get("tokens", []):
                            if token.get("mint") == token_address:
                                token_balance = int(token.get("amount", 0))
                                decimals = token.get("decimals", 9)
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
                                    return result  # Don't retry - no route won't change
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
                        signed = self.wallet.default_address.sign_transaction(tx_base64)
                        
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
                                print(f"Blockhash expired, retry {attempt + 1}")
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
