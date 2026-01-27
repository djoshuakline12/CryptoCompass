import os
import asyncio
import aiohttp
from datetime import datetime, timezone

# Base chain constants (keeping for reference)
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC = "https://mainnet.base.org"

# Solana constants
USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_API = "https://quote-api.jup.ag/v6"

class DexTrader:
    def __init__(self):
        self.cdp = None
        self.account = None
        self.solana_account = None
        self.initialized = False
        self.wallet_address = None  # Base
        self.solana_address = None  # Solana
        self.chain = "solana"  # Default to Solana
        
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
            
            # Try to create Solana account
            try:
                self.solana_account = await self.cdp.solana.get_or_create_account(name=f"{account_name}-SOL")
                self.solana_address = self.solana_account.address
                print(f"✅ Solana account ready: {self.solana_address}")
                self.chain = "solana"
            except Exception as e:
                print(f"⚠️  Solana account error: {e}")
                # Fall back to Base/EVM
                self.account = await self.cdp.evm.get_or_create_account(name=account_name)
                self.wallet_address = self.account.address
                print(f"✅ Base account ready: {self.wallet_address}")
                self.chain = "base"
            
            self.initialized = True
            return True
            
        except Exception as e:
            print(f"❌ CDP init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def get_balances(self) -> dict:
        result = {"sol": 0, "usdc": 0, "eth": 0, "chain": self.chain}
        
        try:
            if self.chain == "solana" and self.solana_address:
                # Get Solana balances via RPC
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
                    
                    # USDC balance (SPL token)
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
                            
            elif self.wallet_address:
                # Base chain balances
                async with aiohttp.ClientSession() as session:
                    eth_payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_getBalance",
                        "params": [self.wallet_address, "latest"],
                        "id": 1
                    }
                    async with session.post(BASE_RPC, json=eth_payload) as resp:
                        data = await resp.json()
                        if "result" in data:
                            wei = int(data["result"], 16)
                            result["eth"] = wei / 1e18
                    
                    usdc_data = "0x70a08231" + self.wallet_address[2:].zfill(64)
                    usdc_payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [{"to": USDC_BASE, "data": usdc_data}, "latest"],
                        "id": 2
                    }
                    async with session.post(BASE_RPC, json=usdc_payload) as resp:
                        data = await resp.json()
                        if "result" in data and data["result"] != "0x":
                            raw = int(data["result"], 16)
                            result["usdc"] = raw / 1e6
                        
        except Exception as e:
            print(f"Balance error: {e}")
            result["error"] = str(e)
        
        return result
    
    async def get_jupiter_quote(self, input_mint: str, output_mint: str, amount: int) -> dict:
        """Get swap quote from Jupiter"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{JUPITER_API}/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps=100"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        print(f"Jupiter quote error: {resp.status}")
                        return None
        except Exception as e:
            print(f"Jupiter quote error: {e}")
            return None
    
    async def swap_usdc_to_token(self, token_address: str, amount_usdc: float) -> dict:
        """Swap USDC to a token"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            if self.chain == "solana":
                print(f"🔄 Solana swap: ${amount_usdc} USDC -> {token_address[:8]}...")
                
                # Convert to smallest unit (USDC has 6 decimals)
                amount_raw = int(amount_usdc * 1e6)
                
                # Get Jupiter quote
                quote = await self.get_jupiter_quote(USDC_SOLANA, token_address, amount_raw)
                if not quote:
                    return {"success": False, "error": "Could not get quote"}
                
                print(f"   Quote: {quote.get('outAmount')} tokens")
                
                # Execute swap via CDP
                try:
                    swap_result = await self.cdp.solana.trade(
                        address=self.solana_address,
                        from_token=USDC_SOLANA,
                        to_token=token_address,
                        amount=str(amount_raw),
                        slippage_percent=1.0
                    )
                    print(f"✅ Swap executed: {swap_result}")
                    return {"success": True, "result": str(swap_result)}
                except Exception as e:
                    print(f"CDP trade error: {e}")
                    return {"success": False, "error": str(e)}
            else:
                # Base chain swap
                print(f"🔄 Base swap: ${amount_usdc} USDC -> {token_address[:10]}...")
                amount_raw = int(amount_usdc * 1e6)
                
                trade = await self.cdp.evm.trade(
                    address=self.wallet_address,
                    from_token=USDC_BASE,
                    to_token=token_address,
                    amount=str(amount_raw),
                    slippage_percent=1.0
                )
                print(f"✅ Swap executed: {trade}")
                return {"success": True, "result": str(trade)}
                
        except Exception as e:
            print(f"❌ Swap error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def swap_token_to_usdc(self, token_address: str, amount_tokens: float = None) -> dict:
        """Swap token back to USDC (sell)"""
        if not self.initialized:
            return {"success": False, "error": "DEX not initialized"}
        
        try:
            if self.chain == "solana":
                print(f"🔄 Solana sell: {token_address[:8]}... -> USDC")
                
                # Get token balance if not specified
                if amount_tokens is None:
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
                                return {"success": False, "error": "No token balance"}
                            
                            info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            amount_raw = int(info.get("tokenAmount", {}).get("amount", 0))
                else:
                    # Assume 9 decimals for most Solana tokens
                    amount_raw = int(amount_tokens * 1e9)
                
                if amount_raw == 0:
                    return {"success": False, "error": "No tokens to sell"}
                
                # Execute swap via CDP
                try:
                    swap_result = await self.cdp.solana.trade(
                        address=self.solana_address,
                        from_token=token_address,
                        to_token=USDC_SOLANA,
                        amount=str(amount_raw),
                        slippage_percent=2.0
                    )
                    print(f"✅ Sell executed: {swap_result}")
                    return {"success": True, "result": str(swap_result)}
                except Exception as e:
                    print(f"CDP sell error: {e}")
                    return {"success": False, "error": str(e)}
            else:
                # Base chain sell
                print(f"🔄 Base sell: {token_address[:10]}... -> USDC")
                
                # Get token balance
                async with aiohttp.ClientSession() as session:
                    token_data = "0x70a08231" + self.wallet_address[2:].zfill(64)
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [{"to": token_address, "data": token_data}, "latest"],
                        "id": 1
                    }
                    async with session.post(BASE_RPC, json=payload) as resp:
                        data = await resp.json()
                        if "result" in data and data["result"] != "0x":
                            amount_raw = int(data["result"], 16)
                        else:
                            return {"success": False, "error": "Could not get token balance"}
                
                if amount_raw == 0:
                    return {"success": False, "error": "No tokens to sell"}
                
                trade = await self.cdp.evm.trade(
                    address=self.wallet_address,
                    from_token=token_address,
                    to_token=USDC_BASE,
                    amount=str(amount_raw),
                    slippage_percent=2.0
                )
                print(f"✅ Sell executed: {trade}")
                return {"success": True, "result": str(trade)}
                
        except Exception as e:
            print(f"❌ Sell error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

dex_trader = DexTrader()
