import aiohttp

class TransactionSimulator:
    async def can_sell_token(self, contract_address: str, wallet_address: str) -> dict:
        result = {"can_sell": True, "error": None, "simulated": False}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://public.jupiterapi.com/quote?inputMint={contract_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=1000"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("outAmount"):
                            result["can_sell"] = True
                            result["simulated"] = True
                        else:
                            result["can_sell"] = False
                            result["error"] = "No route"
                    else:
                        text = await resp.text()
                        if "no route" in text.lower():
                            result["can_sell"] = False
                            result["error"] = "No sell route"
        except:
            pass
        return result

tx_simulator = TransactionSimulator()
