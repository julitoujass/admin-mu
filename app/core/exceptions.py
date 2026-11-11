class StockError(Exception):
    def __init__(self, message: str):
        self.message = message


class CajaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


class UsuarioError(Exception):
    """Business rule violation in user management (404 / 400 / 409)."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
