"""
Erros padronizados do Broker Gateway
"""
from enum import Enum
from typing import Any, Optional


class ErrorCodes(str, Enum):
    """Códigos de erro padronizados"""
    CONNECTION_FAILED = "CONNECTION_FAILED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    TIMEOUT = "TIMEOUT"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    MARKET_CLOSED = "MARKET_CLOSED"
    WEBSOCKET_ERROR = "WEBSOCKET_ERROR"
    HEARTBEAT_FAILED = "HEARTBEAT_FAILED"
    RECONNECTION_FAILED = "RECONNECTION_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class BrokerError(Exception):
    """Erro padronizado do broker"""

    def __init__(
        self,
        message: str,
        code: ErrorCodes = ErrorCodes.UNKNOWN_ERROR,
        broker: Optional[str] = None,
        connection_id: Optional[str] = None,
        request_id: Optional[str] = None,
        original_error: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.broker = broker
        self.connection_id = connection_id
        self.request_id = request_id
        self.original_error = original_error

    def to_dict(self) -> dict:
        """Converte erro para dicionário"""
        return {
            "name": self.__class__.__name__,
            "message": self.message,
            "code": self.code.value if isinstance(self.code, Enum) else self.code,
            "broker": self.broker,
            "connection_id": self.connection_id,
            "request_id": self.request_id,
        }


class ConnectionError(BrokerError):
    """Erro de conexão"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCodes.CONNECTION_FAILED, **kwargs)


class AuthenticationError(BrokerError):
    """Erro de autenticação"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCodes.AUTHENTICATION_FAILED, **kwargs)


class TimeoutError(BrokerError):
    """Erro de timeout"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCodes.TIMEOUT, **kwargs)


class OrderError(BrokerError):
    """Erro de ordem"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCodes.ORDER_REJECTED, **kwargs)


class NotSupportedError(BrokerError):
    """Operação não suportada"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=ErrorCodes.NOT_SUPPORTED, **kwargs)