"""
Modelos padronizados para o Broker Gateway
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AccountType(str, Enum):
    """Tipos de conta"""
    PRACTICE = "practice"
    REAL = "real"
    DEMO = "demo"


class ConnectionStatus(str, Enum):
    """Status da conexão"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    READY = "ready"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class OrderDirection(str, Enum):
    """Direção da ordem"""
    CALL = "CALL"
    PUT = "PUT"


class OrderStatus(str, Enum):
    """Status da ordem"""
    CREATED = "created"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OPEN = "open"
    CLOSED = "closed"
    ERROR = "error"
    TIMEOUT = "timeout"


class OrderResultType(str, Enum):
    """Resultado da ordem"""
    WIN = "WIN"
    LOSS = "LOSS"
    DRAW = "DRAW"


class AssetType(str, Enum):
    """Tipo de ativo"""
    BINARY = "binary"
    DIGITAL = "digital"
    FOREX = "forex"
    CRYPTO = "crypto"
    CFD = "cfd"


class AssetStatus(str, Enum):
    """Status do ativo"""
    OPEN = "open"
    CLOSED = "closed"


class Account(BaseModel):
    """Modelo padronizado de conta"""
    id: Optional[str] = None
    broker: Optional[str] = None
    type: AccountType = AccountType.PRACTICE
    currency: str = "BRL"
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Balance(BaseModel):
    """Modelo padronizado de saldo"""
    available: float = 0.0
    currency: str = "BRL"
    total: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Asset(BaseModel):
    """Modelo padronizado de ativo"""
    symbol: str
    name: Optional[str] = None
    type: AssetType = AssetType.BINARY
    status: AssetStatus = AssetStatus.CLOSED
    payout: float = 0.0
    min_amount: float = 0.0
    max_amount: float = 0.0
    expiration: List[int] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Candle(BaseModel):
    """Modelo padronizado de candle"""
    asset: str
    timeframe: str = "M1"
    timestamp: int = Field(default_factory=lambda: int(datetime.utcnow().timestamp()))
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: Optional[float] = None


class OrderRequest(BaseModel):
    """Modelo padronizado de requisição de ordem"""
    idempotency_key: UUID = Field(default_factory=uuid4)
    asset: str
    direction: OrderDirection
    amount: float
    expiration: int = 1  # minutos
    account_type: AccountType = AccountType.PRACTICE
    connection_id: Optional[str] = None
    request_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class OrderResponse(BaseModel):
    """Modelo padronizado de resposta de ordem"""
    id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    broker: Optional[str] = None
    connection_id: Optional[str] = None
    request_id: Optional[UUID] = None
    idempotency_key: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = None

    class Config:
        use_enum_values = True


class OrderResult(BaseModel):
    """Modelo padronizado de resultado de ordem"""
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    result: Optional[OrderResultType] = None
    profit: float = 0.0
    payout: float = 0.0
    amount: float = 0.0
    direction: Optional[OrderDirection] = None
    asset: Optional[str] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    broker: Optional[str] = None
    connection_id: Optional[str] = None

    class Config:
        use_enum_values = True


class Connection(BaseModel):
    """Modelo de conexão com broker"""
    id: UUID = Field(default_factory=uuid4)
    user_id: Optional[str] = None
    broker: str
    account_type: AccountType = AccountType.PRACTICE
    enabled: bool = True
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True


class BrokerConfig(BaseModel):
    """Configuração de conexão com broker"""
    email: str
    password: str
    account_type: AccountType = AccountType.PRACTICE
    country_code: Optional[int] = None
    proxies: Optional[Dict[str, str]] = None

    class Config:
        use_enum_values = True