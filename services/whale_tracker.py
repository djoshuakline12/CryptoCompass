import aiohttp
import os
from datetime import datetime, timezone, timedelta

# Known profitable Solana meme traders (public wallets from leaderboards)
WHALE_WALLETS = [
    "JDdH5gvnAjPvYoEhEKNsWLpqoGnXsNmvWh1wvPgMaRt8",  # Top trader 1
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Pump.fun deployer
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",  # Known whale
]

class WhaleTracker:
    def __init__(self):
        self.recent_whale_buys = {}  # contract -> {wallets: [], last_seen: datetime}
        self.last_scan = None
        self.helius_key = os.getenv("HELIUS_API_KEY", "")
    
    async def scan_whale_activity(self) -> dict:
        """Scan whale wallets for recent buys"""
        if self.last_scan and (datetime.now(timezone.utc) - self.last_scan).seconds < 120:
            return self.recent_whale_buys
        
        self.last_scan = datetime.now(timezone.utc)
        
        try:
            async with aiohttp.ClientSession() as session:
                for wallet in WHALE_WALLETS[:5]:  # Limit to avoid rate limits
                    await self._scan_wallet_transactions(session, wallet)
        except Exception as e:
            print(f"Whale scan error: {e}")
        
        return self.recent_whale_buys
    
    async def _scan_wallet_transactions(self, session: aiohttp.ClientSession, wallet: str):
        """Get recent transactions for a wallet"""
        try:
            if self.helius_key:
                # Use Helius for better data
                url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions?api-key={self.helius_key}&limit=20"
            else:
                # Fallback to Solscan public API
                url = f"https://public-api.solscan.io/account/transactions?account={wallet}&limit=20"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    txns = data if isinstance(data, list) else data.get("data", [])
                    
                    for tx in txns:
                        await self._parse_transaction(tx, wallet)
        except:
            pass
    
    async def _parse_transaction(self, tx: dict, wallet: str):
        """Parse a transaction to find token buys"""
        try:
            # Look for token transfers or swaps
            tx_type = tx.get("type", "").upper()
            description = tx.get("description", "").lower()
            
            # Check if it's a buy (swap USDC/SOL for token)
            if "swap" in tx_type.lower() or "swap" in description:
                # Get the token being bought
                token_transfers = tx.get("tokenTransfers", [])
                for transfer in token_transfers:
                    mint = transfer.get("mint", "")
                    # If wallet received tokens (not USDC/SOL), it's a buy
                    if mint and mint not in ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "So11111111111111111111111111111111111111112"]:
                        if transfer.get("toUserAccount") == wallet:
                            self._record_whale_buy(mint, wallet)
        except:
            pass
    
    def _record_whale_buy(self, contract: str, wallet: str):
        """Record a whale buy"""
        if contract not in self.recent_whale_buys:
            self.recent_whale_buys[contract] = {
                "wallets": [],
                "count": 0,
                "last_seen": datetime.now(timezone.utc)
            }
        
        if wallet not in self.recent_whale_buys[contract]["wallets"]:
            self.recent_whale_buys[contract]["wallets"].append(wallet)
            self.recent_whale_buys[contract]["count"] += 1
        
        self.recent_whale_buys[contract]["last_seen"] = datetime.now(timezone.utc)
    
    def get_whale_score(self, contract_address: str) -> dict:
        """Get whale activity score for a token"""
        if contract_address not in self.recent_whale_buys:
            return {"score": 0, "whale_count": 0, "recent": False}
        
        data = self.recent_whale_buys[contract_address]
        whale_count = len(data.get("wallets", []))
        
        # Check if recent (last 30 min)
        last_seen = data.get("last_seen")
        recent = False
        if last_seen:
            age_min = (datetime.now(timezone.utc) - last_seen).seconds / 60
            recent = age_min < 30
        
        # Score: 25 points per whale, bonus for recent
        score = min(whale_count * 25, 75)
        if recent:
            score += 25
        
        return {
            "score": min(score, 100),
            "whale_count": whale_count,
            "recent": recent
        }

whale_tracker = WhaleTracker()
