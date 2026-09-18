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
)
from ...core.errors import BrokerError, ErrorCodes


class IQOptionAdapter(BrokerAdapter):
    """Adapter para IQ Option"""

    # Lock global para serializar logins (lib iqoptionapi usa module-level globals
    # que não suportam múltiplas sessões simultâneas). Conexões são feitas uma por vez.
    _login_lock: Optional[asyncio.Lock] = None

    def __init__(self):
        self._api = None
        self._connected = False
        self._authenticated = False
        self._account_type = AccountType.PRACTICE
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._email: Optional[str] = None
        self._password: Optional[str] = None
        self._cached_balance = 0.0
        self._cached_profile = {}
        if IQOptionAdapter._login_lock is None:
            IQOptionAdapter._login_lock = asyncio.Lock()

    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Conecta ao IQ Option.

        IMPORTANTE: a lib iqoptionapi usa globals em `iqoptionapi.global_value`
        (SSID, balance_id) que são compartilhados por todas as instâncias IQ_Option.
        Isso significa que múltiplas conexões simultâneas não funcionam — uma
        segunda conexão reusa o SSID da primeira (api.py:847-850).

        Para suportar múltiplos usuários sequencialmente:
        1. Lock global garante que apenas UM login ocorre por vez
        2. Resetamos os globals ANTES de criar o novo IQ_Option, forçando
           re-autenticação com as credenciais novas
        3. Fechamos explicitamente o WebSocket anterior para limpar estado
        """
        async with self._login_lock:
            try:
                from iqoptionapi.stable_api import IQ_Option
                import iqoptionapi.global_value as gv

                self._email = config.get("email")
                self._password = config.get("password")
                account_type = config.get("account_type", "practice")

                if not self._email or not self._password:
                    raise BrokerError(
                        "Email and password are required",
                        code=ErrorCodes.INVALID_CREDENTIALS,
                        broker="iqoption",
                    )

                # Resetar globals da lib — sem isso, IQ_Option.connect() reusa o SSID
                # da sessão anterior (api.py:847-850: "doing temp ssid reconnect for speed up")
                gv.SSID = None
                gv.balance_id = None
                gv.check_websocket_if_connect = None
                gv.check_websocket_if_error = False
                gv.websocket_error_reason = None

                self._api = IQ_Option(self._email, self._password)

                # Connect - roda em background thread, o while loop da lib
                # pode demorar mas vai completar quando o WebSocket receber dados
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._api.connect),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    # Timeout nos while loops internos, mas o WebSocket pode estar conectado
                    pass

                # Verificar se está conectado
                try:
                    is_connected = await asyncio.wait_for(
                        asyncio.to_thread(self._api.check_connect),
                        timeout=5.0,
                    )
                    if not is_connected:
                        self._api = None
                        raise BrokerError(
                            "Failed to connect to IQ Option.",
                            code=ErrorCodes.CONNECTION_FAILED,
                            broker="iqoption",
                        )
                except asyncio.TimeoutError:
                    self._api = None
                    raise BrokerError(
                        "Connection check timeout.",
                        code=ErrorCodes.TIMEOUT,
                        broker="iqoption",
                    )

                self._connected = True
                self._authenticated = True

                balance_mode = self._resolve_balance_mode(account_type)
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._api.change_balance, balance_mode),
                        timeout=10.0,
                    )
                except Exception as e:
                    print(f"[IQOption] change_balance({balance_mode}) failed: {e}")
                    raise BrokerError(
                        f"Failed to switch to {balance_mode} account",
                        code=ErrorCodes.CONNECTION_FAILED,
                        broker="iqoption",
                        original_error=e,
                    )

                self._account_type = AccountType(account_type)

                return {
                    "status": ConnectionStatus.READY.value,
                    "broker": "iqoption",
                    "account_type": account_type,
                    "balance_mode": balance_mode,
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
                # Clean up on error
                self._api = None
                self._connected = False
                self._authenticated = False
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
        """Obtém informações da conta"""
        self._ensure_connected()

        try:
            profile_msg = None
            try:
                profile_msg = self._api.api.profile.msg
            except Exception:
                pass

            if profile_msg:
                return Account(
                    id=str(profile_msg.get("id", "")),
                    broker="iqoption",
                    type=self._account_type,
                    currency=profile_msg.get("currency", "USD"),
                    status=ConnectionStatus.READY,
                )

            return Account(
                id="",
                broker="iqoption",
                type=self._account_type,
                currency="USD",
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
        """Obtém saldo da conta - lê do cache do WebSocket"""
        self._ensure_connected()

        try:
            amount = None
            try:
                # get_balance() sem argumentos - assinatura correta
                raw_balance = await asyncio.to_thread(self._api.get_balance)
                if raw_balance and isinstance(raw_balance, (int, float)):
                    amount = float(raw_balance)
            except Exception:
                pass

            # Fallback: tentar leitura do cache do WebSocket se disponivel
            if amount is None:
                try:
                    import iqoptionapi.global_value as gv
                    raw = self._api.api.balances_raw
                    if raw is not None:
                        obj_id = self._api.api.object_id
                        current_balance_id = gv.balance_id.get(obj_id)
                        for bal in raw.get("msg", []):
                            if bal["id"] == current_balance_id:
                                amount = float(bal["amount"])
                                break
                except Exception:
                    pass

            return Balance(
                available=amount if amount is not None else 0.0,
                currency="USD",
                total=amount if amount is not None else 0.0,
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
            # Obter ativos abertos - assinatura correta: get_all_open_time() sem args
            assets = []
            try:
                all_assets = await asyncio.to_thread(self._api.get_all_open_time)
            except Exception:
                all_assets = None

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
            all_assets = await asyncio.to_thread(self._api.get_all_open_time)
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

            # Enviar ordem - assinatura correta: buy(price, ACTIVES, ACTION, expirations)
            # price: valor da aposta, ACTIVES: ativo, ACTION: 1=CALL 0=PUT, expirations: tempo
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

    @staticmethod
    def _resolve_balance_mode(account_type: str) -> str:
        """
        Mapeia AccountType interno (practice/demo/real) para o
        Balance_MODE aceito pela iqoptionapi (PRACTICE | REAL | TOURNAMENT).
        'demo' é tratado como 'practice' pois a IQ Option não tem conta demo
        separada — apenas a conta virtual PRACTICE.
        """
        mode = (account_type or "practice").lower()
        if mode in ("practice", "demo"):
            return "PRACTICE"
        if mode == "real":
            return "REAL"
        return "PRACTICE"

    async def _get_asset_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtém dados do ativo diretamente da API"""
        try:
            all_assets = await asyncio.to_thread(self._api.get_all_open_time)
            if all_assets and "turbo" in all_assets and symbol in all_assets["turbo"]:
                return all_assets["turbo"][symbol]
        except Exception:
            pass
        return None
