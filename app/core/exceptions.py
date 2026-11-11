class StockError(Exception):
    def __init__(self, message: str):
        self.message = message


class CajaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
