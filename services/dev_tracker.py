class DevWalletTracker:
    def __init__(self):
        self.dev_wallets = {}
        self.dev_selling = set()
    
    async def is_dev_selling(self, contract_address: str) -> dict:
        return {"is_selling": False, "dev_wallet": "", "warning": None}
    
    def is_known_dev_seller(self, contract_address: str) -> bool:
        return contract_address in self.dev_selling

dev_tracker = DevWalletTracker()
