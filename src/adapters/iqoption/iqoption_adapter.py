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
    OrderResultType,
    OrderStatus,
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
        self._last_order_amounts: Dict[str, float] = {}
        self._wait_result_timeout_sec = 380.0
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
                # change_balance depende do profile WS (get_profile_ansyc) que
                # chega de forma assíncrona logo após o login — tentar 3x com
                # backoff para não falhar por race de settle.
                switched = False
                last_err: Optional[Exception] = None
                for attempt in range(3):
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(self._api.change_balance, balance_mode),
                            timeout=10.0,
                        )
                        switched = True
                        break
                    except Exception as e:
                        last_err = e
                        print(f"[IQOption] change_balance({balance_mode}) tentativa {attempt + 1}/3 falhou: {e!r}", flush=True)
                        await asyncio.sleep(2.0 * (attempt + 1))
                if not switched:
                    raise BrokerError(
                        f"Failed to switch to {balance_mode} account",
                        code=ErrorCodes.CONNECTION_FAILED,
                        broker="iqoption",
                        original_error=last_err,
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
                    self._format_connect_error(e),
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
        await self._ensure_live_session()

        try:
            amount = None
            try:
                # get_balance() tem while-loops da lib sem proteção — race com
                # timeout próprio para não travar a rota quando a ws cai
                raw_balance = await asyncio.wait_for(
                    asyncio.to_thread(self._api.get_balance),
                    timeout=15.0,
                )
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
                        current_balance_id = gv.balance_id
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
            seen: Dict[str, Asset] = {}
            try:
                all_assets = await asyncio.wait_for(
                    asyncio.to_thread(self._api.get_all_open_time),
                    timeout=25.0,
                )
            except asyncio.TimeoutError:
                all_assets = None

            # Verificar se retornou dados validos
            if not isinstance(all_assets, dict):
                return assets

            # Agregar buckets de opções binárias (turbo/binary/digital).
            # OTC geralmente está em "binary"; prioridade ao bucket com open=True.
            for bucket in ("turbo", "binary", "digital"):
                entries = all_assets.get(bucket)
                if not isinstance(entries, dict):
                    continue
                for symbol, data in entries.items():
                    if not isinstance(data, dict):
                        continue
                    is_open = bool(data.get("open", False))
                    payout = float(data.get("payout", 0) or 0)
                    existing = seen.get(symbol)
                    if existing is None:
                        seen[symbol] = Asset(
                            symbol=symbol,
                            name=symbol,
                            type=AssetType.BINARY,
                            status=AssetStatus.OPEN if is_open else AssetStatus.CLOSED,
                            payout=payout,
                            min_amount=1,
                            max_amount=1000,
                            expiration=[1, 5],
                        )
                    elif is_open and not existing.status == AssetStatus.OPEN:
                        # Bucket posterior confirma aberto — atualizar status/payout
                        seen[symbol] = Asset(
                            symbol=symbol,
                            name=symbol,
                            type=AssetType.BINARY,
                            status=AssetStatus.OPEN,
                            payout=max(payout, existing.payout),
                            min_amount=1,
                            max_amount=1000,
                            expiration=[1, 5],
                        )

            assets = list(seen.values())
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
            data = await self._get_asset_data(symbol)
            if isinstance(data, dict):
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
            if asset_data and not asset_data.get("open", False):
                raise BrokerError(
                    f"Asset {order.asset} is closed",
                    code=ErrorCodes.MARKET_CLOSED,
                    broker="iqoption",
                )
            if asset_data is None and not self._is_otc(order.asset):
                # Ativo regular não encontrado no book em nenhum bucket:
                # tratar como fechado para falhar rápido e claro.
                raise BrokerError(
                    f"Asset {order.asset} not found or market closed",
                    code=ErrorCodes.MARKET_CLOSED,
                    broker="iqoption",
                )
            # OTC não encontrado no book: segue a operação mesmo assim e
            # deixa a IQ Option responder (rejeição real, se houver).

            # Direção: buyv3 da lib faz direction.lower() esperando "call"/"put"
            direction = "call" if order.direction == OrderDirection.CALL else "put"

            result = await self._send_buy(order.amount, order.asset, direction, order.expiration)
            print(f"[IQOption] buy raw result={result!r}", flush=True)

            if result and result[0]:
                order_id = str(result[1])
                self._last_order_amounts[order_id] = float(order.amount or 0.0)
                return OrderResponse(
                    id=order_id,
                    status=OrderStatus.ACCEPTED,
                    broker="iqoption",
                    connection_id=order.connection_id,
                    request_id=order.request_id,
                    idempotency_key=order.idempotency_key,
                )
            else:
                # buy() devolve (False, message) — preservar o motivo real
                # (ex: 'insufficient balance', 'asset expired', etc.)
                reason = None
                if isinstance(result, (list, tuple)) and len(result) > 1:
                    reason = str(result[1]) if result[1] is not None else None
                print(f"[IQOption] order rejected for {order.asset}: reason={reason!r}")
                return OrderResponse(
                    status=OrderStatus.REJECTED,
                    broker="iqoption",
                    connection_id=order.connection_id,
                    request_id=order.request_id,
                    idempotency_key=order.idempotency_key,
                    error=reason or "Order rejected by broker (sem mensagem do broker)",
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

    async def _send_buy(
        self,
        amount: float,
        symbol: str,
        direction: str,
        expiration: int,
    ) -> tuple:
        """
        Envia uma ordem binária com janela de ACK própria (12s).

        O stable_api.buy() da lib desiste em 5s ('buy late 5 sec') mesmo
        quando a IQ Option processa a ordem — causando falsas rejeições.
        Replicamos o mesmo fluxo (buyv3 + buy_multi_option) com espera
        mais longa:
          - (True, order_id) quando o ws devolve a posição
          - (False, message) quando o broker devolve erro explícito
          - (False, None) se estourar a janela
        """
        import random

        req_id = str(random.randint(100000, 999999))
        api_raw = self._api.api

        def _send():
            from iqoptionapi import OP_code as _OP

            active_id = _OP.ACTIVES.get(symbol)
            if active_id is None:
                raise BrokerError(
                    f"Unknown active: {symbol}",
                    code=ErrorCodes.ASSET_NOT_FOUND,
                    broker="iqoption",
                )
            api_raw.buyv3(float(amount), active_id, direction, int(expiration), req_id)

        api_raw.buy_multi_option = {req_id: {}}
        await asyncio.to_thread(_send)

        deadline = asyncio.get_event_loop().time() + 12.0
        while asyncio.get_event_loop().time() < deadline:
            payload = api_raw.buy_multi_option.get(req_id) or {}
            if payload.get("id"):
                return True, str(payload["id"])
            if payload.get("message"):
                return False, payload["message"]
            await asyncio.sleep(0.2)
        return False, None

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

    async def _ensure_live_session(self) -> None:
        """
        Garante WebSocket vivo para leituras dependentes de socket
        (ex: check_win_v4). Reconecta UMA vez com as credenciais
        armazenadas se a sessão caiu (login válido, não depende de
        senha errada).
        """
        try:
            alive = bool(await asyncio.to_thread(self._api.check_connect))
        except Exception:
            alive = False
        if alive:
            return

        print("[IQOption] WebSocket morto ao consultar ordem — reconectando...", flush=True)
        auth_type = self._account_type.value if hasattr(self._account_type, 'value') else str(self._account_type)
        await self.connect({
            "email": self._email,
            "password": self._password,
            "account_type": auth_type,
        })

    async def get_order(self, order_id: str) -> OrderResponse:
        """
        Obtém status de uma ordem binária.

        USA check_win_v4 da lib (socket_option_closed): enquanto a opção
        está em aberto, retorna PENDING; quando fecha, retorna CLOSED.
        """
        self._ensure_connected()
        await self._ensure_live_session()

        result = self._query_order_result_blocking(order_id)
        if result is not None:
            return OrderResponse(
                id=order_id,
                status=OrderStatus.CLOSED,
                broker="iqoption",
            )
        return OrderResponse(
            id=order_id,
            status=OrderStatus.OPEN,
            broker="iqoption",
        )

    async def get_order_result(self, order_id: str) -> OrderResult:
        """
        Obtém o resultado final (WIN/LOSS/DRAW) de uma ordem binária.

        Bloqueia (em thread separada) até a opção fechar via check_win_v4.
        Múltiplas consultas simultâneas para o mesmo id são ok: cada thread
        espera o payload do WebSocket e as seguintes retornam instantâneas.
        """
        self._ensure_connected()
        await self._ensure_live_session()
        return self._query_order_result_blocking(order_id)

    def _query_order_result_blocking(self, order_id: str) -> OrderResult:
        """
        Chama check_win_v4 (bloqueante até o fechamento) e mapeia
        ('win'|'loose'|'equal', profit) para OrderResult.
        """
        import threading

        holder: Dict[str, Any] = {"error": None}
        done = threading.Event()

        def _worker():
            try:
                win, profit = self._api.check_win_v4(order_id)
                holder["win"] = win
                holder["profit"] = profit
            except Exception as exc:  # pragma: no cover - lib interna
                holder["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        # Não trava o event loop indefinidamente: espera até 6min + folga
        if not done.wait(timeout=(self._wait_result_timeout_sec)):
            raise BrokerError(
                "Timed out waiting for order result",
                code=ErrorCodes.TIMEOUT,
                broker="iqoption",
            )

        if holder.get("error"):
            raise BrokerError(
                f"Failed to get order result: {holder['error']}",
                code=ErrorCodes.UNKNOWN_ERROR,
                broker="iqoption",
                original_error=holder["error"],
            )

        win = str(holder.get("win", "")).lower()
        profit = float(holder.get("profit") or 0.0)

        if win == "win":
            result_type = OrderResultType.WIN
        elif win == "loose":
            result_type = OrderResultType.LOSS
        else:
            result_type = OrderResultType.DRAW

        return OrderResult(
            order_id=order_id,
            status=OrderStatus.CLOSED,
            result=result_type,
            profit=profit,
            payout=round(profit / self._last_amount(order_id) * 100, 2) if profit and self._last_amount(order_id) else 0.0,
        )

    def _last_amount(self, order_id: str) -> float:
        """Valor apostado na ordem (armazenado em place_order) para derivar payout."""
        return self._last_order_amounts.get(order_id, 0.0)

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

    @staticmethod
    def _format_connect_error(e: Exception) -> str:
        """
        Formata o erro de conexão para o usuário.

        Bug conhecido da lib iqoptionapi (stable_api.py:142): quando o
        WebSocket falha, `json.loads(reason)` gera um JSONDecodeError
        ("Expecting value: line 1 column 2") que mascara o motivo real
        da falha — que fica em global_value.websocket_error_reason.
        Traduz esses casos para uma mensagem útil.
        """
        msg = str(e)
        try:
            import iqoptionapi.global_value as _gv
            reason = getattr(_gv, "websocket_error_reason", None)
        except Exception:
            reason = None

        if "Expecting value" in msg and reason:
            return f"IQ Option inacessível (WebSocket): {reason}"
        if "Expecting value" in msg:
            return (
                "IQ Option inacessível (WebSocket): não foi possível conectar a "
                "iqoption.com. Verifique rede/proxy/firewall."
            )
        return f"Connection error: {msg}"

    async def _get_asset_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Obtém dados de abertura do ativo em múltiplos buckets.

        get_all_open_time() retorna: {"binary": {...}, "turbo": {...},
        "digital": {...}, "cfd": {...}, "forex": {...}, ...} e pares OTC
        frequentemente aparecem em "binary" (não só em "turbo").
        Preferência: primeiro registro com open=True entre os buckets;
        se o ativo existir apenas com open=False, retorna esse registro
        (o chamador decide rejeitar).

        Nota: a lib tem um bug em que chunk de dados digital não chega e
        o loop interno trava — por isso a chamada roda com timeout e,
        expirando, devolvemos None (o chamador decide o fallback).
        """
        try:
            all_assets = await asyncio.wait_for(
                asyncio.to_thread(self._api.get_all_open_time),
                timeout=25.0,
            )
            if not isinstance(all_assets, dict):
                return None

            fallback: Optional[Dict[str, Any]] = None
            for bucket in ("turbo", "binary", "digital"):
                entries = all_assets.get(bucket)
                if not isinstance(entries, dict) or symbol not in entries:
                    continue
                data = entries.get(symbol)
                if not isinstance(data, dict):
                    continue
                if data.get("open", False):
                    return data
                if fallback is None:
                    fallback = data
            return fallback
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    def _is_otc(self, symbol: str) -> bool:
        """Assets '-OTC' da IQ Option têm mercado permanente (não seguem o horário)."""
        return symbol.strip().upper().endswith("-OTC")
