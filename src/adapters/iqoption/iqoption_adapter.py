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

    def __init__(self):
        self._api = None
        self._connected = False
        self._authenticated = False
        self._login_lock: asyncio.Lock = asyncio.Lock()
        self._last_order_amounts: Dict[str, float] = {}
        self._wait_result_timeout_sec = 380.0
        self._account_type = AccountType.PRACTICE
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._email: Optional[str] = None
        self._password: Optional[str] = None
        self._cached_balance = 0.0
        self._cached_profile = {}
        # Cache de get_all_init_v2 (turbo/binary actives) — evita bloquear
        # ordens/assets no while-loop da lib (pode não responder na sessão longa).
        self._init_v2_cache: Optional[Dict[str, Any]] = None
        self._init_v2_cache_at: float = 0.0
        self._init_v2_lock: asyncio.Lock = asyncio.Lock()
        # Task periódica: mantém cache de ativos quente e detecta queda de
        # sessão (auto-heal com backoff).
        self._refresh_task: Optional[asyncio.Task] = None
        import os as _os
        try:
            self._refresh_interval_sec = float(_os.environ.get("IQ_REFRESH_SEC", "300"))
        except ValueError:
            self._refresh_interval_sec = 300.0

    def _format_login_reason(self, reason: Optional[str]) -> str:
        """
        Traduz o motivo de falha de login da IQ Option para uma mensagem
        clara em PT-BR, preservando o detalhe original. reason pode ser
        JSON ('{"result":false,"message":"...","code":"..."}') ou texto.
        """
        raw = (reason or "").strip()
        detail = ""
        code = ""
        message = ""
        if raw:
            try:
                import json as _json
                parsed = _json.loads(raw)
                if isinstance(parsed, dict):
                    code = str(parsed.get("code", "") or "")
                    message = str(parsed.get("message", "") or "")
            except Exception:
                # texto cru da lib (ex: 'Websocket connection closed.')
                message = raw
            detail = message if message else raw

        lowered = (code + " " + message).lower()

        if ("invalid" in lowered or "wrong" in lowered or "incorrect" in lowered) and (
            "credential" in lowered or "password" in lowered or "login" in lowered
        ):
            friendly = "E-mail ou senha incorretos. NÃO tente novamente sem confirmar as credenciais — tentativas repetidas bloqueiam seu IP."
        elif "duplicate" in lowered:
            friendly = "Sessão duplicada: esta conta já está conectada em outra sessão."
        elif ("2fa" in lowered or "verify" in lowered or "sms" in lowered):
            friendly = "Verificação 2FA/por e-mail exigida pela IQ Option."
        elif "banned" in lowered or "block" in lowered:
            friendly = "Conta ou IP bloqueado pela IQ Option. Aguarde antes de tentar novamente."
        elif "too_many" in lowered or "too many" in lowered or "attempt" in lowered or "rate" in lowered or "limit" in lowered:
            friendly = "Muitas tentativas de login — IP temporariamente bloqueado. Aguarde antes de tentar."
        elif "maintenance" in lowered:
            friendly = "IQ Option em manutenção no momento."
        else:
            ws_reason = self._get_ws_error_reason()
            if raw and raw in ("Websocket connection closed.", ""):
                friendly = "Falha de rede encontra a IQ Option (WebSocket não respondeu)."
            elif ws_reason:
                friendly = f"Falha no login (WebSocket): {ws_reason}"
            else:
                friendly = "Falha no login. Verifique rede/credenciais antes de tentar novamente."

        return f"{friendly} [motivo: {detail or 'não informado pelo broker'}]" if detail else friendly

    def _get_ws_error_reason(self) -> Optional[str]:
        """Lê websocket_error_reason do estado indexado por object_id (fork victalejo)."""
        try:
            import iqoptionapi.global_value as _gv
            if isinstance(_gv.websocket_error_reason, dict):
                if self._api and getattr(self._api.api, "object_id", None) is not None:
                    return _gv.websocket_error_reason.get(self._api.api.object_id)
                return next((v for v in _gv.websocket_error_reason.values() if v), None)
            return getattr(_gv, "websocket_error_reason", None)
        except Exception:
            return None

    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Conecta ao IQ Option.

        A lib iqoptionapi (fork victalejo) indexa o estado global por
        object_id/id(wss) — cada instância IQ_Option mantém SSID, balance_id,
        locks e buffers próprios. Múltiplas sessões simultâneas são suportadas.

        O lock por instância evita apenas connect() concorrente na MESMA
        instância (ex: auto-reconnect disputando com um connect manual).
        """
        async with self._login_lock:
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

                self._api = IQ_Option(self._email, self._password)

                # Connect - roda em background thread, o while loop da lib
                # pode demorar mas vai completar quando o WebSocket receber dados.
                # CAPTURA o retorno (ok, reason): o motivo real de falha de
                # login vem aqui (senha errada, conta bloqueada, 2FA etc.) e
                # NÃO pode ser descartado — evita retries cegos que bloqueiam
                # o IP na corretora.
                connect_ok = None
                connect_reason: Optional[str] = None
                try:
                    _ok, _reason = await asyncio.wait_for(
                        asyncio.to_thread(self._api.connect),
                        timeout=30.0,
                    )
                    connect_ok = _ok
                    connect_reason = _reason if isinstance(_reason, str) else None
                except asyncio.TimeoutError:
                    # Timeout nos while loops internos, mas o WebSocket pode estar conectado
                    pass

                if connect_ok is False:
                    # Login negado pelo broker — surface o motivo real
                    self._api = None
                    self._connected = False
                    self._authenticated = False
                    reason = self._format_login_reason(connect_reason)
                    print(f"[IQOption] login negado: {reason}", flush=True)
                    raise BrokerError(
                        reason,
                        code=ErrorCodes.INVALID_CREDENTIALS,
                        broker="iqoption",
                    )

                # Verificar se está conectado
                try:
                    is_connected = await asyncio.wait_for(
                        asyncio.to_thread(self._api.check_connect),
                        timeout=5.0,
                    )
                    if not is_connected:
                        self._api = None
                        self._connected = False
                        self._authenticated = False
                        reason = self._format_login_reason(None)
                        raise BrokerError(
                            reason,
                            code=ErrorCodes.CONNECTION_FAILED,
                            broker="iqoption",
                        )
                except asyncio.TimeoutError:
                    self._api = None
                    self._connected = False
                    self._authenticated = False
                    raise BrokerError(
                        "Connection check timeout: IQ Option não confirmou o WebSocket em 30s.",
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

                # Aquece cache de ativos logo após o login — sessões longas
                # podem não responder a get-initialization-data de novo.
                try:
                    import time as _time
                    warm = await asyncio.wait_for(
                        asyncio.to_thread(self._api.get_all_init_v2, 0.2),
                        timeout=10.0,
                    )
                    if isinstance(warm, dict) and warm:
                        self._init_v2_cache = warm
                        self._init_v2_cache_at = _time.time()
                    print(
                        f"[IQOption] init_v2 warmup "
                        f"{'ok' if self._init_v2_cache else 'falhou'}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[IQOption] init_v2 warmup skip: {e!r}", flush=True)

                # Task periódica: refresh de ativos + auto-heal da sessão
                self._start_refresh_task()

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
        await self._stop_refresh_task()
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
                self._init_v2_cache = None
                self._init_v2_cache_at = 0.0

    # ------------------------------------------------------------------
    # Task periódica: refresh de ativos + auto-heal
    # ------------------------------------------------------------------

    def _start_refresh_task(self) -> None:
        """Cria (se necessário) a task de refresh/auto-heal da sessão."""
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._assets_refresh_loop())

    async def _stop_refresh_task(self) -> None:
        """Cancela a task de refresh (usado no disconnect/shutdown)."""
        task = self._refresh_task
        self._refresh_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _assets_refresh_loop(self) -> None:
        """
        Loop periódico (intervalo via env IQ_REFRESH_SEC, padrão 300s):
        - mantém o cache de ativos quente (fetch forçado a cada tick);
        - verifica a saúde do WebSocket (check_connect) e reconecta com
          backoff quando a sessão cai (auto-heal).
        Desiste após MAX_HEAL_ATTEMPTS falhas seguidas — reconexão manual.
        """
        import time as _time

        max_heal_attempts = 5
        failures = 0
        print(
            f"[IQOption] refresh task iniciada (intervalo={self._refresh_interval_sec:.0f}s)",
            flush=True,
        )
        try:
            while True:
                # Backoff progressivo em falhas; base no sucesso.
                if failures == 0:
                    wait = self._refresh_interval_sec
                else:
                    wait = min(60.0 * (2 ** min(failures - 1, 3)), 600.0)
                await asyncio.sleep(wait)

                if not self._email or not self._password:
                    # Desconectado manualmente / sem credenciais — encerra.
                    break

                try:
                    alive = False
                    if self._api and self._connected:
                        try:
                            alive = bool(
                                await asyncio.wait_for(
                                    asyncio.to_thread(self._api.check_connect),
                                    timeout=5.0,
                                )
                            )
                        except Exception:
                            alive = False

                    if alive:
                        failures = 0
                        # Sessão OK: atualiza cache de ativos (max_age=0 força
                        # fetch novo; o lock coalescing evita rajadas).
                        await self._fetch_init_v2(timeout_sec=8.0, max_age_sec=0.0)
                        print(
                            f"[IQOption] refresh task: cache de ativos atualizado "
                            f"({_time.strftime('%H:%M:%S')})",
                            flush=True,
                        )
                    else:
                        failures += 1
                        if failures > max_heal_attempts:
                            print(
                                "[IQOption] auto-heal desistiu após 5 tentativas — "
                                "reconecte manualmente",
                                flush=True,
                            )
                            break
                        print(
                            f"[IQOption] auto-heal: sessão inativa, reconectando "
                            f"(tentativa {failures}/{max_heal_attempts})",
                            flush=True,
                        )
                        await self._heal_reconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failures += 1
                    print(
                        f"[IQOption] refresh task erro ({failures}): {e!r}",
                        flush=True,
                    )
                    if failures > max_heal_attempts:
                        print(
                            "[IQOption] refresh task desistiu após erros seguidos",
                            flush=True,
                        )
                        break
        except asyncio.CancelledError:
            print("[IQOption] refresh task cancelada", flush=True)
            raise

    async def _heal_reconnect(self) -> None:
        """Derruba a sessão morta e reconecta com as credenciais em cache."""
        if not self._email or not self._password:
            return
        if self._api:
            try:
                await asyncio.to_thread(self._api.disconnect)
            except Exception:
                pass
            self._api = None
            self._connected = False
            self._authenticated = False
        account_type = (
            self._account_type.value
            if hasattr(self._account_type, "value")
            else str(self._account_type or "practice")
        )
        try:
            await self.connect(
                {
                    "email": self._email,
                    "password": self._password,
                    "account_type": account_type,
                }
            )
            print("[IQOption] auto-heal: reconectado com sucesso", flush=True)
        except Exception as e:
            print(f"[IQOption] auto-heal falhou: {e!r}", flush=True)
            raise

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
                        oid = getattr(self._api.api, "object_id", None)
                        if isinstance(gv.balance_id, dict) and oid is not None:
                            current_balance_id = gv.balance_id.get(oid)
                        else:
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

    async def _fetch_init_v2(
        self, timeout_sec: float = 8.0, max_age_sec: float = 90.0, force: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Obtém turbo/binary actives com cache TTL.

        get_all_init_v2 usa while-loop na lib — em sessões longas a resposta
        "initialization-data" pode nunca chegar e o wait estoura. Cache
        evita travar /assets e place_order (antes: 25s por ordem).
        """
        import time as _time

        async with self._init_v2_lock:
            now = _time.time()
            if (
                not force
                and self._init_v2_cache is not None
                and (now - self._init_v2_cache_at) < max_age_sec
            ):
                return self._init_v2_cache

            if not self._api:
                return self._init_v2_cache

            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(self._api.get_all_init_v2, 0.2),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                # Mantém cache anterior se houver (stale better than nothing)
                return self._init_v2_cache

            if isinstance(data, dict) and data:
                self._init_v2_cache = data
                self._init_v2_cache_at = now
                return data
            return self._init_v2_cache

    async def get_assets(self) -> List[Asset]:
        """
        Lista ativos disponíveis

        Returns:
            Lista de ativos
        """
        self._ensure_connected()

        try:
            # get_all_open_time(polling) trava no bucket digital (bug da lib).
            # get_all_init_v2 com cache evita bloqueio em sessão longa.
            assets = []
            seen: Dict[str, Asset] = {}
            all_assets = await self._fetch_init_v2(timeout_sec=8.0)

            if not isinstance(all_assets, dict):
                return assets

            # Agregar buckets turbo/binary/blitz (OTC e mercado regular).
            # Blitz é o mercado de curto prazo atual (M1-M5); binary = Digital.
            for bucket in ("turbo", "binary", "blitz"):
                block = all_assets.get(bucket)
                if not isinstance(block, dict):
                    continue
                entries = block.get("actives")
                if not isinstance(entries, dict):
                    continue
                for _aid, active in entries.items():
                    if not isinstance(active, dict):
                        continue
                    raw_name = str(active.get("name", "") or "")
                    symbol = raw_name.split(".")[-1] if raw_name else ""
                    if not symbol:
                        continue
                    is_open = bool(active.get("enabled")) and not bool(
                        active.get("is_suspended")
                    )
                    existing = seen.get(symbol)
                    if existing is None:
                        seen[symbol] = Asset(
                            symbol=symbol,
                            name=symbol,
                            type=AssetType.BINARY,
                            status=AssetStatus.OPEN if is_open else AssetStatus.CLOSED,
                            payout=0,
                            min_amount=1,
                            max_amount=1000,
                            expiration=[1, 5],
                        )
                    elif is_open:
                        seen[symbol] = Asset(
                            symbol=symbol,
                            name=symbol,
                            type=AssetType.BINARY,
                            status=AssetStatus.OPEN,
                            payout=existing.payout,
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
            # Verificar se ativo está aberto (cache TTL — não bloqueia ordem).
            # Com expiration: M1-M5 checam turbo/Blitz; >5min checam binary/Digital.
            asset_data = await self._get_asset_data(order.asset, order.expiration)
            if asset_data and not asset_data.get("open", False):
                if asset_data.get("is_suspended"):
                    raise BrokerError(
                        f"Ativo {order.asset} suspenso pela IQ Option "
                        f"(horário/mercado). Escolha outro ativo.",
                        code=ErrorCodes.MARKET_CLOSED,
                        broker="iqoption",
                    )
                raise BrokerError(
                    f"Ativo {order.asset} fechado no momento",
                    code=ErrorCodes.MARKET_CLOSED,
                    broker="iqoption",
                )
            if asset_data is None and not self._is_otc(order.asset):
                # Ativo regular não encontrado no book em nenhum bucket:
                # tratar como fechado para falhar rápido e claro.
                raise BrokerError(
                    f"Ativo {order.asset} não encontrado ou mercado fechado",
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
            import iqoptionapi.constants as _OP

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

        result = await self._query_order_result_blocking(order_id)
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
        return await self._query_order_result_blocking(order_id)

    async def _query_order_result_blocking(self, order_id: str) -> OrderResult:
        """
        Chama check_win_v4 (bloqueante até o fechamento) e mapeia
        ('win'|'loose'|'equal', profit) para OrderResult.
        O wait roda em thread para não congelar o event loop (as demais
        sessões continuam respondendo enquanto uma aguarda resultado).
        """
        import threading

        holder: Dict[str, Any] = {"error": None}
        done = threading.Event()

        def _worker():
            try:
                # socket_option_closed é indexado pelo ID NUMÉRICO do ws
                # (msg["id"] int) — passar string casara KeyError silencioso
                # e a thread esperaria eternamente.
                oid = int(order_id)
                win, profit = self._api.check_win_v4(oid)
                holder["win"] = win
                holder["profit"] = profit
            except Exception as exc:  # pragma: no cover - lib interna
                holder["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        # Espera em thread separada para não bloquear o event loop
        finished = await asyncio.to_thread(done.wait, self._wait_result_timeout_sec)
        if not finished:
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
        reason = None
        try:
            import iqoptionapi.global_value as _gv
            if isinstance(_gv.websocket_error_reason, dict):
                reason = next((v for v in _gv.websocket_error_reason.values() if v), None)
            else:
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

    async def _get_asset_data(
        self, symbol: str, expiration: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Obtém estado do ativo (enabled/is_suspended) nos buckets init_v2.

        Usa cache get_all_init_v2 (TTL 90s). Timeout curto para não atrasar
        place_order (antes: 25s por ordem quando a lib não respondia).

        Com expiration: ordens M1-M5 (buyv3 option_type_id=3) são do mercado
        curto prazo (turbo/Blitz) — status vem de turbo+blitz; ordens >5min
        (binary/Digital) vêm do bucket binary. Sem expiration: qualquer bucket.
        Retorna {"open": bool, "is_suspended": bool, ...}.
        """
        try:
            all_assets = await self._fetch_init_v2(timeout_sec=6.0)
            if not isinstance(all_assets, dict):
                return None

            if expiration is None:
                primary: tuple = ("turbo", "binary", "blitz")
                secondary: tuple = ()
            elif int(expiration) <= 5:
                primary, secondary = ("turbo", "blitz"), ("binary",)
            else:
                primary, secondary = ("binary",), ("turbo", "blitz")

            def _scan(buckets):
                first_closed = None
                for bucket in buckets:
                    block = all_assets.get(bucket)
                    if not isinstance(block, dict):
                        continue
                    entries = block.get("actives")
                    if not isinstance(entries, dict):
                        continue
                    for _aid, active in entries.items():
                        if not isinstance(active, dict):
                            continue
                        raw_name = str(active.get("name", "") or "")
                        name = raw_name.split(".")[-1] if raw_name else ""
                        if name != symbol:
                            continue
                        is_open = bool(active.get("enabled")) and not bool(
                            active.get("is_suspended")
                        )
                        data = {
                            "open": is_open,
                            "enabled": bool(active.get("enabled")),
                            "is_suspended": bool(active.get("is_suspended")),
                            "name": raw_name,
                            "bucket": bucket,
                        }
                        if is_open:
                            return data
                        if first_closed is None:
                            first_closed = data
                return first_closed

            result = _scan(primary)
            if result is None:
                result = _scan(secondary)
            return result
        except Exception:
            return None

    def _is_otc(self, symbol: str) -> bool:
        """Assets '-OTC' da IQ Option têm mercado permanente (não seguem o horário)."""
        return symbol.strip().upper().endswith("-OTC")
