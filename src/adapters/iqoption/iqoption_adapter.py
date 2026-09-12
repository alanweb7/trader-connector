"""
Adapter para IQ Option
Utiliza a biblioteca iqoptionapi para conexão com a plataforma
"""
import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from ...core.interfaces.broker_adapter import BrokerAdapter
from ...core.models import (
    Account,
    AccountType,
    Asset,
    AssetStatus,
    AssetType,
    Balance,
    BrokerConfig,
    Candle,
    ConnectionStatus,
    OrderDirection,
    OrderRequest,
    OrderResponse,
    OrderResult,
    OrderStatus,
)
from ...core.errors import BrokerError, ErrorCodes


class IQOptionAdapter(BrokerAdapter):
    """Adapter para IQ Option"""

    def __init__(self):
        self._api = None
        self._connected = False
        self._authenticated = False
        self._account_type = AccountType.PRACTICE
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._email: Optional[str] = None
        self._password: Optional[str] = None

    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Conecta ao IQ Option
        
        Args:
            config: Configuração com email, password, account_type
            
        Returns:
            Status da conexão
        """
        try:
            from iqoptionapi.stable_api import IQ_Option

            self._email = config.get("email")
            self._password = config.get("password")
            account_type = config.get("account_type", "practice")

            if not self._email or not self._password:
                raise BrokerError(
                    "Email and password are required",
                    code=ErrorCodes.INVALID_CREDENTIALS,
                    broker="iqoption",
                )

            # Criar instância da API
            self._api = IQ_Option(self._email, self._password)

            # Conectar
            result = await asyncio.to_thread(self._api.connect)
            if not result:
                raise BrokerError(
                    "Failed to connect to IQ Option",
                    code=ErrorCodes.CONNECTION_FAILED,
                    broker="iqoption",
                )

            # Mudar para conta practice se solicitado
            if account_type == "practice":
                await asyncio.to_thread(self._api.change_balance, "PRACTICE")
            else:
                await asyncio.to_thread(self._api.change_balance, "REAL")

            self._connected = True
            self._authenticated = True
            self._account_type = AccountType(account_type)

            return {
                "status": ConnectionStatus.READY.value,
                "broker": "iqoption",
                "account_type": account_type,
                "message": "Connected successfully",
            }

        except ImportError:
            raise BrokerError(
                "iqoptionapi library not installed. Run: pip install iqoptionapi",
                code=ErrorCodes.NOT_SUPPORTED,
                broker="iqoption",
            )
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(
                f"Connection error: {str(e)}",
                code=ErrorCodes.CONNECTION_FAILED,
                broker="iqoption",
                original_error=e,
            )

    async def disconnect(self) -> None:
        """Desconecta do IQ Option"""
        if self._api:
            try:
                await asyncio.to_thread(self._api.disconnect)
            except Exception:
                pass
            finally:
                self._api = None
                self._connected = False
                self._authenticated = False
                self._subscriptions.clear()

    async def get_status(self) -> Dict[str, Any]:
        """
        Obtém status da conexão
        
        Returns:
            Status atual
        """
        if not self._api:
            return {"status": ConnectionStatus.DISCONNECTED.value}

        try:
            is_connected = await asyncio.to_thread(self._api.check_connect)
            return {
                "status": ConnectionStatus.READY.value if is_connected else ConnectionStatus.DISCONNECTED.value,
                "broker": "iqoption",
                "account_type": self._account_type.value,
            }
        except Exception as e:
            return {
                "status": ConnectionStatus.ERROR.value,
                "error": str(e),
            }

    async def get_account(self) -> Account:
        """
        Obtém informações da conta
        
        Returns:
            Dados da conta
        """
        self._ensure_connected()

        try:
            profile = await asyncio.to_thread(self._api.get_profile)
            return Account(
                id=str(profile.get("id", "")),
                broker="iqoption",
                type=self._account_type,
                currency=profile.get("currency", "USD"),
                status=ConnectionStatus.READY,
            )
        except Exception as e:
            raise BrokerError(
                f"Failed to get account: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def get_balance(self) -> Balance:
        """
        Obtém saldo da conta
        
        Returns:
            Saldo atual
        """
        self._ensure_connected()

        try:
            balance = await asyncio.to_thread(self._api.get_balance)
            return Balance(
                available=float(balance),
                currency="USD",
                total=float(balance),
                updated_at=datetime.utcnow(),
            )
        except Exception as e:
            raise BrokerError(
                f"Failed to get balance: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def get_assets(self) -> List[Asset]:
        """
        Lista ativos disponíveis
        
        Returns:
            Lista de ativos
        """
        self._ensure_connected()

        try:
            # Obter ativos abertos (roda em thread para nao bloquear)
            assets = []
            all_assets = await asyncio.to_thread(self._api.get_all_open_time, True)

            # Verificar se retornou dados validos
            if all_assets is None:
                # Mercado pode estar fechado - retornar lista vazia
                return assets

            if isinstance(all_assets, dict) and "turbo" in all_assets:
                for symbol, data in all_assets["turbo"].items():
                    if isinstance(data, dict):
                        asset = Asset(
                            symbol=symbol,
                            name=symbol,
                            type=AssetType.BINARY,
                            status=AssetStatus.OPEN if data.get("open", False) else AssetStatus.CLOSED,
                            payout=data.get("payout", 0),
                            min_amount=1,
                            max_amount=1000,
                            expiration=[1, 5],
                        )
                        assets.append(asset)

            return assets

        except Exception as e:
            raise BrokerError(
                f"Failed to get assets: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def get_asset(self, symbol: str) -> Asset:
        """
        Obtém informações de um ativo específico
        
        Args:
            symbol: Símbolo do ativo
            
        Returns:
            Dados do ativo
        """
        self._ensure_connected()

        try:
            all_assets = await asyncio.to_thread(self._api.get_all_open_time, True)
            if all_assets and "turbo" in all_assets and symbol in all_assets["turbo"]:
                data = all_assets["turbo"][symbol]
                return Asset(
                    symbol=symbol,
                    name=symbol,
                    type=AssetType.BINARY,
                    status=AssetStatus.OPEN if data.get("open", False) else AssetStatus.CLOSED,
                    payout=data.get("payout", 0),
                    min_amount=1,
                    max_amount=1000,
                    expiration=[1, 5],
                )

            raise BrokerError(
                f"Asset {symbol} not found",
                code=ErrorCodes.ASSET_NOT_FOUND,
                broker="iqoption",
            )

        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(
                f"Failed to get asset: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def get_candles(
        self, asset: str, timeframe: int, count: int
    ) -> List[Candle]:
        """
        Obtém candles históricos
        
        Args:
            asset: Ativo
            timeframe: Timeframe em minutos
            count: Quantidade de candles
            
        Returns:
            Lista de candles
        """
        self._ensure_connected()

        try:
            # Converter timeframe para segundos
            interval = timeframe * 60

            # Obter timestamp final
            end_time = await asyncio.to_thread(self._api.get_server_timestamp)

            # Obter candles
            candles_data = await asyncio.to_thread(
                self._api.get_candles, asset, interval, count, end_time
            )

            candles = []
            if candles_data:
                for candle in candles_data:
                    candles.append(
                        Candle(
                            asset=asset,
                            timeframe=f"M{timeframe}",
                            timestamp=candle.get("from", 0),
                            open=candle.get("open", 0),
                            high=candle.get("max", 0),
                            low=candle.get("min", 0),
                            close=candle.get("close", 0),
                            volume=candle.get("volume", None),
                        )
                    )

            return candles

        except Exception as e:
            raise BrokerError(
                f"Failed to get candles: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def subscribe_candles(
        self, asset: str, timeframe: int, callback: Callable
    ) -> str:
        """
        Inscreve-se para receber candles em tempo real
        
        Args:
            asset: Ativo
            timeframe: Timeframe em minutos
            callback: Função de retorno
            
        Returns:
            ID da inscrição
        """
        self._ensure_connected()

        subscription_id = str(uuid4())

        # Armazenar inscrição
        self._subscriptions[subscription_id] = {
            "asset": asset,
            "timeframe": timeframe,
            "callback": callback,
            "active": True,
        }

        # TODO: Implementar streaming real de candles
        # A biblioteca iqoptionapi pode não suportar streaming assíncrono diretamente
        # Necessário verificar documentação ou implementar polling

        return subscription_id

    async def unsubscribe_candles(self, subscription_id: str) -> None:
        """
        Cancela inscrição de candles
        
        Args:
            subscription_id: ID da inscrição
        """
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id]["active"] = False
            del self._subscriptions[subscription_id]

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Envia ordem
        
        Args:
            order: Dados da ordem
            
        Returns:
            Resposta da ordem
        """
        self._ensure_connected()

        try:
            # Verificar se ativo está aberto
            asset_data = await self._get_asset_data(order.asset)
            if not asset_data or not asset_data.get("open", False):
                raise BrokerError(
                    f"Asset {order.asset} is closed",
                    code=ErrorCodes.MARKET_CLOSED,
                    broker="iqoption",
                )

            # Converter direção
            direction = 1 if order.direction == OrderDirection.CALL else 0

            # Enviar ordem
            result = await asyncio.to_thread(
                self._api.buy, order.amount, order.asset, direction, order.expiration
            )

            if result and result[0]:
                order_id = str(result[1])
                return OrderResponse(
                    id=order_id,
                    status=OrderStatus.ACCEPTED,
                    broker="iqoption",
                    connection_id=order.connection_id,
                    request_id=order.request_id,
                    idempotency_key=order.idempotency_key,
                )
            else:
                return OrderResponse(
                    status=OrderStatus.REJECTED,
                    broker="iqoption",
                    connection_id=order.connection_id,
                    request_id=order.request_id,
                    idempotency_key=order.idempotency_key,
                    error="Order rejected by broker",
                )

        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(
                f"Failed to place order: {str(e)}",
                code=ErrorCodes.ORDER_REJECTED,
                broker="iqoption",
                original_error=e,
            )

    async def get_order(self, order_id: str) -> OrderResponse:
        """
        Obtém status de uma ordem
        
        Args:
            order_id: ID da ordem
            
        Returns:
            Dados da ordem
        """
        self._ensure_connected()

        try:
            # A biblioteca pode não ter método direto para obter ordem
            # Retornar status básico
            return OrderResponse(
                id=order_id,
                status=OrderStatus.OPEN,
                broker="iqoption",
            )
        except Exception as e:
            raise BrokerError(
                f"Failed to get order: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def get_order_result(self, order_id: str) -> OrderResult:
        """
        Obtém resultado de uma ordem
        
        Args:
            order_id: ID da ordem
            
        Returns:
            Resultado da ordem
        """
        self._ensure_connected()

        try:
            # Tentar obter resultado
            # A biblioteca pode ter métodos específicos para isso
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                broker="iqoption",
            )
        except Exception as e:
            raise BrokerError(
                f"Failed to get order result: {str(e)}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=e,
            )

    async def cancel_order(self, order_id: str) -> None:
        """
        Cancela uma ordem
        
        Args:
            order_id: ID da ordem
        """
        self._ensure_connected()

        # IQ Option pode não suportar cancelamento direto
        raise BrokerError(
            "Order cancellation not supported by IQ Option",
            code=ErrorCodes.NOT_SUPPORTED,
            broker="iqoption",
        )

    def _ensure_connected(self) -> None:
        """Verifica se está conectado"""
        if not self._connected or not self._api:
            raise BrokerError(
                "Not connected to IQ Option",
                code=ErrorCodes.CONNECTION_FAILED,
                broker="iqoption",
            )

    async def _get_asset_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtém dados do ativo diretamente da API"""
        try:
            all_assets = await asyncio.to_thread(self._api.get_all_open_time, True)
            if all_assets and "turbo" in all_assets and symbol in all_assets["turbo"]:
                return all_assets["turbo"][symbol]
        except Exception:
            pass
        return None