import os
import json
import asyncio
import aiohttp
import base64
from datetime import datetime, timezone

class DexTrader:
    def __init__(self):
        self.initialized = False
        self.client = None
        self.solana_address = "BQVcTBUUHRcniikRzyfmddzkkUtDABkASvaVua13Yq4n"
        self.chain = "solana"
        self.last_trade_time = None
        self.min_trade_interval = 5
        self.pending_trades = set()
        self.can_sign = False
    
    async def initialize(self):
        """Initialize CDP wallet"""
        try:
            api_key = os.getenv("CDP_API_KEY_NAME")
            api_secret = os.getenv("CDP_API_KEY_SECRET", "").replace("\\n", "\n")
            
            if not api_key or not api_secret:
                print("❌ Missing CDP API credentials")
                return False
            
            # Initialize CDP client
            from cdp import CdpClient
            self.client = CdpClient(api_key_id=api_key, api_key_secret=api_secret)
            
            # Try to get Solana signing capability
            try:
                # Check what Solana functions are available
                from cdp import solana_client
                print(f"🔍 solana_client contents: {[x for x in dir(solana_client) if not x.startswith('_')][:10]}")
                
                # Try to create/get a Solana account
                if hasattr(solana_client, 'SolanaClient'):
                    sc = solana_client.SolanaClient(self.client)
                    print(f"🔍 SolanaClient methods: {[x for x in dir(sc) if not x.startswith('_')][:10]}")
            except Exception as e:
                print(f"Solana client exploration: {e}")
            
            # For now, we'll use the Jupiter API with the address
            # Trading will work once we figure out signing
            self.initialized = True
            print(f"✅ Solana account ready: {self.solana_address}")
            print(f"⚠️ Signing: Exploring CDP SDK capabilities...")
            return True
            
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
        """Swap USDC to token using CDP SDK"""
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
            # Try using CDP SDK's Solana trading capability
            try:
                from cdp.actions import solana as solana_actions
                print(f"🔍 solana_actions: {[x for x in dir(solana_actions) if not x.startswith('_')]}")
                
                # Look for swap or trade function
                if hasattr(solana_actions, 'swap'):
                    tx = await solana_actions.swap(
                        self.client,
                        from_token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        to_token=token_address,
                        amount=int(amount_usdc * 1e6),
                        wallet_address=self.solana_address
                    )
                    result["success"] = True
                    result["tx_hash"] = str(tx)
                    return result
            except Exception as e:
                print(f"CDP swap attempt: {e}")
            
            # Fallback: Try using Jupiter with CDP signing
            async with aiohttp.ClientSession() as session:
                amount_raw = int(amount_usdc * 1e6)
                quote_url = f"https://public.jupiterapi.com/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={amount_raw}&slippageBps=200"
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        result["error"] = f"Quote failed: {resp.status}"
                        return result
                    quote = await resp.json()
                
                if not quote.get("outAmount"):
                    result["error"] = "No route found"
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
                        return result
                    swap_data = await resp.json()
                
                if not swap_data.get("swapTransaction"):
                    result["error"] = "No transaction returned"
                    return result
                
                tx_base64 = swap_data["swapTransaction"]
                
                # Try to sign with CDP
                try:
                    from cdp.solana_account import SolanaServerAccount
                    # Get or create account
                    account = SolanaServerAccount(self.client, address=self.solana_address)
                    signed = account.sign_transaction(tx_base64)
                    
                    # Send transaction
                    rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
                    send_body = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sendTransaction",
                        "params": [signed, {"skipPreflight": True, "maxRetries": 3}]
                    }
                    
                    async with session.post(rpc_url, json=send_body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        send_result = await resp.json()
                    
                    if "error" in send_result:
                        result["error"] = str(send_result["error"])[:100]
                        return result
                    
                    result["success"] = True
                    result["tx_hash"] = send_result.get("result", "")
                    self.last_trade_time = datetime.now(timezone.utc)
                    return result
                    
                except Exception as e:
                    result["error"] = f"Signing failed: {str(e)[:80]}"
                    return result
                    
        except Exception as e:
            result["error"] = str(e)[:100]
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
            
            # Get quote and build transaction
            async with aiohttp.ClientSession() as session:
                quote_url = f"https://public.jupiterapi.com/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount={token_balance}&slippageBps=300"
                
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        result["error"] = f"Quote failed: {resp.status}"
                        return result
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
                        return result
                    swap_data = await resp.json()
                
                if not swap_data.get("swapTransaction"):
                    result["error"] = "No transaction"
                    return result
                
                tx_base64 = swap_data["swapTransaction"]
                
                # Try to sign with CDP
                try:
                    from cdp.solana_account import SolanaServerAccount
                    account = SolanaServerAccount(self.client, address=self.solana_address)
                    signed = account.sign_transaction(tx_base64)
                    
                    rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
                    send_body = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sendTransaction",
                        "params": [signed, {"skipPreflight": True, "maxRetries": 3}]
                    }
                    
                    async with session.post(rpc_url, json=send_body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        send_result = await resp.json()
                    
                    if "error" in send_result:
                        result["error"] = str(send_result["error"])[:100]
                        return result
                    
                    result["success"] = True
                    result["tx_hash"] = send_result.get("result", "")
                    self.last_trade_time = datetime.now(timezone.utc)
                    return result
                    
                except Exception as e:
                    result["error"] = f"Signing failed: {str(e)[:80]}"
                    return result
                    
        except Exception as e:
            result["error"] = str(e)[:100]
        finally:
            self.pending_trades.discard(trade_key)
        
        return result

dex_trader = DexTrader()
