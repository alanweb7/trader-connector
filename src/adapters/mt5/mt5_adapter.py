"""
Adapter ponte para a B3 via API local MetaTrader 5 (broker "mt5").

O terminal MT5 (Windows) roda numa VPS com a API desta pasta /MT5-API; este
adapter faz proxy HTTP/WS para ela, permitindo que conexões broker="mt5"
usem os MESMOS endpoints do gateway (/connections/{id}/candles,
/ws/connections/{id}) sem tocar nos adapters IQ Option/Polarium.

Escopo: SOMENTE DADOS (candles/quote/símbolos). Ordens/saldo não existem
nesta fase — place_order/cancel_order lançam NotSupportedError.

Catálogo: o módulo B3 expõe apenas 2 ativos (WIN e BIT). A API MT5 devolve
em /api/v1/catalog o id estável (WIN/BIT), o símbolo do terminal (WIN$/BIT$)
e o contrato vigente (WINZ26/BITX26); a API resolve o id → símbolo nos
candles/cotações.

Configuração:
    MT5_API_URL  URL base da API B3/MT5 (default http://127.0.0.1:8001).
                 Em produção com CONNECTOR em container, use o IP da VPS
                 Windows que hospeda o MT5 (ex.: http://10.0.0.5:8001).

Criação de conexão (sem credenciais — a autenticação é a sessão do MT5):
    POST /connections  {"broker": "mt5", "name": "B3 Toro"}
"""
import asyncio
import inspect
import os
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import httpx

from ...core.errors import BrokerError, ErrorCodes, NotSupportedError
from ...core.interfaces.broker_adapter import BrokerAdapter
from ...core.models import (
    Account,
    Asset,
    AssetStatus,
    AssetType,
    Balance,
    Candle,
    ConnectionStatus,
    OrderRequest,
    OrderResponse,
    OrderResult,
)

# minutos inteiros (formato do gateway) -> nome de timeframe da API MT5
MINUTES_TO_MT5: Dict[int, str] = {
    1: "M1", 2: "M2", 3: "M3", 4: "M4", 5: "M5", 6: "M6",
    10: "M10", 12: "M12", 15: "M15", 20: "M20", 30: "M30",
    60: "H1", 120: "H2", 180: "H3", 240: "H4", 360: "H6", 480: "H8",
    720: "H12", 1440: "D1", 10080: "W1", 43200: "MN1",
}


def timeframe_to_mt5(timeframe: int) -> str:
    """Converte minutos (formato do gateway) para nome MT5 ('M1', 'H1'...)."""
    name = MINUTES_TO_MT5.get(int(timeframe))
    if not name:
        supported = ", ".join(f"{m}min" for m in sorted(MINUTES_TO_MT5))
        raise BrokerError(
            f"Timeframe {timeframe}min não suportado pela B3/MT5 "
            f"(suportados: {supported})",
            code=ErrorCodes.NOT_SUPPORTED,
            broker="mt5",
        )
    return name


class MT5BridgeAdapter(BrokerAdapter):
    """Ponte gateway <-> API B3/MT5 (somente dados)."""

    BROKER_NAME = "mt5"
    DEFAULT_BASE_URL = "http://127.0.0.1:8001"
    REQUEST_TIMEOUT_SEC = 20.0
    WS_OPEN_TIMEOUT_SEC = 10.0
    # backoff entre tentativas de reconexão do stream (segundos)
    WS_RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._base_url = (
            os.getenv("MT5_API_URL") or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        # sub_id -> {"task", "asset", "timeframe"}
        self._subs: Dict[str, Dict[str, Any]] = {}
        self._sub_seq = 0

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self.REQUEST_TIMEOUT_SEC),
            )
        return self._client

    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Valida alcance da API B3/MT5 e do terminal MT5 (sem credenciais)."""
        # Override opcional por conexão (POST /connections aceita "host")
        override = (config or {}).get("mt5_api_url") or (config or {}).get("host")
        if override:
            self._base_url = str(override).rstrip("/")

        try:
            health = await self._request("GET", "/health")
        except BrokerError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BrokerError(
                f"API B3/MT5 em {self._base_url} indisponível: {e}. "
                "Verifique se o serviço b3-mt5-api está rodando na VPS Windows "
                "(junto ao terminal MT5) e se MT5_API_URL está correto.",
                code=ErrorCodes.CONNECTION_FAILED,
                broker=self.BROKER_NAME,
            ) from e

        if not (health.get("mt5") or {}).get("connected"):
            raise BrokerError(
                f"Terminal MT5 indisponível em {self._base_url} "
                f"({health.get('status')}). Abra/logue o MT5 da Toro na VPS.",
                code=ErrorCodes.CONNECTION_FAILED,
                broker=self.BROKER_NAME,
            )

        self._connected = True
        account = health.get("mt5") or {}
        return {
            "status": "connected",
            "broker": self.BROKER_NAME,
            "server": account.get("server"),
        }

    async def disconnect(self) -> None:
        for sub_id in list(self._subs.keys()):
            await self.unsubscribe_candles(sub_id)
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._connected = False

    async def get_status(self) -> Dict[str, Any]:
        if not self._connected:
            return {"status": "disconnected", "broker": self.BROKER_NAME}
        try:
            health = await self._request("GET", "/health")
            ok = bool((health.get("mt5") or {}).get("connected"))
            return {
                "status": "connected" if ok else "error",
                "broker": self.BROKER_NAME,
                "source": self._base_url,
                "mt5": health.get("mt5"),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "status": "error",
                "broker": self.BROKER_NAME,
                "source": self._base_url,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Conta / saldo (limitado — conexão de dados)
    # ------------------------------------------------------------------

    async def get_account(self) -> Account:
        health = await self._request("GET", "/health")
        info = health.get("mt5") or {}
        return Account(
            id=str(info.get("login") or "mt5"),
            broker=self.BROKER_NAME,
            type="real",
            currency=info.get("currency") or "BRL",
            status=(
                ConnectionStatus.READY
                if info.get("connected")
                else ConnectionStatus.ERROR
            ),
        )

    async def get_balance(self) -> Balance:
        raise NotSupportedError(
            "Conexão B3 (MT5) é somente de dados — saldo não disponível.",
            broker=self.BROKER_NAME,
        )

    # ------------------------------------------------------------------
    # Ativos
    # ------------------------------------------------------------------

    async def get_assets(self) -> List[Asset]:
        """Catálogo curado do módulo B3: apenas WIN e BIT (ids estáveis).

        A API MT5 expõe /api/v1/catalog com o id estável (WIN/BIT), o símbolo
        do terminal (WIN$/BIT$) e o contrato vigente (WINZ26/BITX26).
        """
        data = await self._request("GET", "/api/v1/catalog")
        assets: List[Asset] = []
        for item in data.get("assets", []):
            asset_id = str(item.get("id") or "").strip()
            if not asset_id:
                continue
            assets.append(
                Asset(
                    symbol=asset_id,
                    name=item.get("name"),
                    type=AssetType.CFD,
                    status=self._asset_status(item),
                )
            )
        return assets

    async def get_asset(self, symbol: str) -> Asset:
        """Detalhes de um ativo do catálogo (id estável ou símbolo do terminal)."""
        wanted = symbol.strip().upper()
        data = await self._request("GET", "/api/v1/catalog")
        for item in data.get("assets", []):
            ids = {
                str(item.get("id") or "").strip().upper(),
                str(item.get("symbol") or "").strip().upper(),
            }
            if wanted in ids:
                return Asset(
                    symbol=str(item.get("id") or wanted),
                    name=item.get("name"),
                    type=AssetType.CFD,
                    status=self._asset_status(item),
                )

        # Fora do catálogo: cotação direta (símbolo cru do terminal).
        quote_data = await self._request(
            "GET", f"/api/v1/quote/{quote(wanted, safe='')}"
        )
        return Asset(
            symbol=quote_data.get("symbol") or wanted,
            name=None,
            type=AssetType.CFD,
            status=AssetStatus.OPEN,
        )

    @staticmethod
    def _asset_status(item: Dict[str, Any]) -> str:
        """Status do ativo no catálogo B3 (open/closed/unknown)."""
        if not item.get("available", True):
            return AssetStatus.UNKNOWN
        status = str(item.get("status") or "").strip().lower()
        if status == "open":
            return AssetStatus.OPEN
        if status == "closed":
            return AssetStatus.CLOSED
        return AssetStatus.UNKNOWN

    # ------------------------------------------------------------------
    # Candles (REST)
    # ------------------------------------------------------------------

    async def get_candles(
        self, asset: str, timeframe: int, count: int, end_time: Optional[int] = None
    ) -> List[Candle]:
        """Histórico via API B3/MT5. end_time = epoch segundos (paginação).

        O id pedido é o do catálogo (WIN/BIT); a API MT5 resolve para o
        símbolo do terminal (WIN$/BIT$). O candle volta com o id estável.
        """
        tf_name = timeframe_to_mt5(timeframe)
        symbol = asset.strip().upper()
        params: Dict[str, Any] = {"timeframe": tf_name, "count": int(count)}
        if end_time is not None:
            params["end_time"] = int(end_time)

        data = await self._request(
            "GET", f"/api/v1/historical/{quote(symbol, safe='')}", params=params
        )
        candles = [self._to_candle(c, tf_name) for c in data.get("candles", [])]
        for candle in candles:
            candle.asset = symbol
        return candles

    # ------------------------------------------------------------------
    # Candles (stream WS — fechamento de vela)
    # ------------------------------------------------------------------

    async def subscribe_candles(
        self, asset: str, timeframe: int, callback: Callable
    ) -> str:
        """Assina o stream WS da API B3/MT5 (evento candle_closed).

        O callback recebe um Candle a cada vela FECHADA (assim como o
        canal candle-generated da IQ). Reconecta com backoff em caso de
        queda; o CandleStreamSession do gateway cobre o fallback REST.
        """
        self._ensure_connected()
        tf_name = timeframe_to_mt5(timeframe)
        symbol = asset.strip().upper()

        self._sub_seq += 1
        sub_id = f"mt5-{self._sub_seq}-{symbol}-{tf_name}"
        task = asyncio.create_task(self._stream_loop(sub_id, symbol, tf_name, callback))
        self._subs[sub_id] = {"task": task, "asset": symbol, "timeframe": tf_name}
        return sub_id

    async def unsubscribe_candles(self, subscription_id: str) -> None:
        entry = self._subs.pop(subscription_id, None)
        if not entry:
            return
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _stream_loop(
        self, sub_id: str, symbol: str, tf_name: str, callback: Callable
    ) -> None:
        """Loop de leitura do WS /api/v1/stream/{symbol} (reconecta sozinho)."""
        import websockets

        ws_base = self._base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        url = f"{ws_base}/api/v1/stream/{quote(symbol, safe='')}?timeframe={tf_name}"
        attempt = 0
        try:
            while True:
                try:
                    async with websockets.connect(
                        url, open_timeout=self.WS_OPEN_TIMEOUT_SEC
                    ) as ws:
                        attempt = 0
                        async for raw in ws:
                            await self._handle_ws_message(raw, symbol, tf_name, callback)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — websockets.* variam por versão
                    if sub_id not in self._subs:
                        return
                    delay = self.WS_RECONNECT_DELAYS[
                        min(attempt, len(self.WS_RECONNECT_DELAYS) - 1)
                    ]
                    attempt += 1
                    print(
                        f"[MT5Bridge] stream {symbol} {tf_name} caiu "
                        f"({e!r}); reconectando em {delay}s",
                        flush=True,
                    )
                    await asyncio.sleep(delay)
        finally:
            self._subs.pop(sub_id, None)

    async def _handle_ws_message(
        self, raw: Any, symbol: str, tf_name: str, callback: Callable
    ) -> None:
        """Converte uma mensagem do stream em Candle e chama o callback."""
        import json

        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(msg, dict):
            return

        msg_type = msg.get("type")
        if msg_type == "error":
            print(
                f"[MT5Bridge] erro no stream {symbol} {tf_name}: "
                f"{msg.get('message')}",
                flush=True,
            )
            return
        if msg_type != "candle_closed":
            return  # ready/ping/snapshot são ignorados pelo gateway

        candle = self._to_candle(msg, tf_name)
        # preserva o id estável do catálogo (WIN/BIT), não o símbolo do terminal
        candle.asset = symbol
        result = callback(candle)
        if inspect.isawaitable(result):
            await result

    # ------------------------------------------------------------------
    # Ordens (fora de escopo — somente dados)
    # ------------------------------------------------------------------

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        raise NotSupportedError(
            "Conexão B3 (MT5) é somente de dados — ordens não suportadas.",
            broker=self.BROKER_NAME,
        )

    async def cancel_order(self, order_id: str) -> None:
        raise NotSupportedError(
            "Conexão B3 (MT5) é somente de dados — ordens não suportadas.",
            broker=self.BROKER_NAME,
        )

    async def get_order(self, order_id: str) -> OrderResult:
        raise NotSupportedError(
            "Conexão B3 (MT5) é somente de dados — ordens não suportadas.",
            broker=self.BROKER_NAME,
        )

    async def get_order_result(self, order_id: str) -> OrderResult:
        raise NotSupportedError(
            "Conexão B3 (MT5) é somente de dados — ordens não suportadas.",
            broker=self.BROKER_NAME,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise BrokerError(
                "Conexão mt5 não conectada (faça POST /connections/{id}/connect)",
                code=ErrorCodes.CONNECTION_FAILED,
                broker=self.BROKER_NAME,
            )

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        try:
            response = await self._http().request(
                method, path, params=params, timeout=timeout
            )
        except httpx.TimeoutException as e:
            raise BrokerError(
                f"Timeout na API B3/MT5 ({self._base_url}{path})",
                code=ErrorCodes.TIMEOUT,
                broker=self.BROKER_NAME,
            ) from e
        except httpx.HTTPError as e:
            raise BrokerError(
                f"API B3/MT5 inacessível ({self._base_url}{path}): {e}",
                code=ErrorCodes.CONNECTION_FAILED,
                broker=self.BROKER_NAME,
            ) from e

        if response.status_code == 404:
            raise BrokerError(
                self._detail(response) or "Recurso não encontrado na API B3/MT5",
                code=ErrorCodes.ASSET_NOT_FOUND,
                broker=self.BROKER_NAME,
            )
        if response.status_code >= 400:
            code = (
                ErrorCodes.MARKET_CLOSED
                if response.status_code == 503
                else ErrorCodes.UNKNOWN_ERROR
            )
            raise BrokerError(
                self._detail(response) or f"HTTP {response.status_code}",
                code=code,
                broker=self.BROKER_NAME,
            )
        return response.json()

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            return str(response.json().get("detail") or "")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _to_candle(payload: Dict[str, Any], tf_name: str) -> Candle:
        return Candle(
            asset=payload.get("asset") or payload.get("symbol") or "",
            timeframe=payload.get("timeframe") or tf_name,
            timestamp=int(payload.get("timestamp") or payload.get("time") or 0),
            open=float(payload.get("open") or 0.0),
            high=float(payload.get("high") or 0.0),
            low=float(payload.get("low") or 0.0),
            close=float(payload.get("close") or 0.0),
            volume=float(payload.get("volume") or 0.0),
        )
