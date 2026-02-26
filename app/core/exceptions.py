class StockError(Exception):
    def __init__(self, message: str):
        self.message = message

class CajaError(Exception):
    def __init__(self, message: str):
        self.message = message
