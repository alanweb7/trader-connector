"""
Sessão WebSocket de streaming de candles do Broker Gateway.

Rota registrada em src/server.py: /ws/connections/{connection_id}

Protocolo (JSON):

  cliente -> servidor:
    {"action": "subscribe",   "asset": "EURUSD-OTC", "timeframe": 1}
    {"action": "unsubscribe", "asset": "EURUSD-OTC", "timeframe": 1}
    {"action": "ping"}

  servidor -> cliente:
    {"type": "ready",       "connection_id": "..."}
    {"type": "subscribed",  "asset", "timeframe", "mode": "live"|"poll"}
    {"type": "unsubscribed","asset", "timeframe"}
    {"type": "candle",      "asset", "timeframe", "candle": {...}, "mode"}
    {"type": "status",      "asset", "timeframe", "mode", "reason"?}
    {"type": "error",       "message", "asset"?, "timeframe"?}
    {"type": "pong"}

Modos:
  live = lib iqoptionapi entregando candle-generated em tempo real
  poll = fallback REST (get_candles count=1, a cada 2s) quando o stream
         não entrega dados no prazo ou a assinatura falhou — o protocolo
         para o cliente é idêntico, só muda o campo "mode".

Toda saída passa por uma única fila/fila -> send_loop, para nunca haver
escritas concorrentes no mesmo WebSocket.
"""
import asyncio
import json
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import WebSocket, WebSocketDisconnect

from ...core.errors import BrokerError

Key = Tuple[str, int]


class CandleStreamSession:
    """Uma sessão WS = um cliente conectado a uma connection."""

    # Sem a 1ª vela "live" nesse prazo -> entra em modo poll
    LIVE_CONFIRM_SEC = 12.0
    # Stream provou funcionar, mas calou por esse prazo -> volta a poll
    LIVE_STALL_SEC = 30.0
    # Intervalo do fallback REST
    POLL_INTERVAL_SEC = 2.0
    # Backoff após falha no fallback REST (evita martelar a sessão)
    POLL_FAILURE_BACKOFF_SEC = 5.0
    # Timeout acima do interno do get_candles (20s) — cancelar no meio
    # vazaria threads do to_thread presas no polling da lib
    POLL_REQUEST_TIMEOUT_SEC = 25.0
    QUEUE_MAX = 1000

    def __init__(self, websocket: WebSocket, connection_id: str, adapter: Any):
        self.ws = websocket
        self.connection_id = connection_id
        self.adapter = adapter
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._subs: Dict[Key, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def run(self) -> None:
        recv_task = asyncio.create_task(self._recv_loop())
        send_task = asyncio.create_task(self._send_loop())
        try:
            done, _pending = await asyncio.wait(
                {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    print(
                        f"[WS] sessão {self.connection_id} encerrada: {exc!r}",
                        flush=True,
                    )
        finally:
            for task in (recv_task, send_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(recv_task, send_task, return_exceptions=True)
            await self._cleanup_subs()

    # ------------------------------------------------------------------
    # Saída serializada (único consumidor da fila -> send)
    # ------------------------------------------------------------------

    def _emit(self, message: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # Sob carga, descarta em vez de bloquear o event loop.
            pass

    async def _send_loop(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self.ws.send_json(message)
            except WebSocketDisconnect:
                return

    # ------------------------------------------------------------------
    # Entrada (mensagens do cliente)
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        while True:
            raw = await self.ws.receive_text()
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                self._emit({"type": "error", "message": "JSON inválido"})
                continue
            if not isinstance(data, dict):
                self._emit({"type": "error", "message": "Mensagem inválida"})
                continue

            action = data.get("action")
            if action == "ping":
                self._emit({"type": "pong"})
                continue

            asset = str(data.get("asset") or "")
            try:
                timeframe = int(data.get("timeframe") or 0)
            except (TypeError, ValueError):
                timeframe = 0
            if not asset or timeframe <= 0:
                self._emit(
                    {"type": "error", "message": "Informe asset e timeframe válidos"}
                )
                continue

            key = (asset, timeframe)
            if action == "subscribe":
                await self._subscribe(key)
            elif action == "unsubscribe":
                await self._unsubscribe(key)
            else:
                self._emit(
                    {
                        "type": "error",
                        "message": f"Action desconhecida: {action!r}",
                    }
                )

    # ------------------------------------------------------------------
    # Assinaturas
    # ------------------------------------------------------------------

    async def _subscribe(self, key: Key) -> None:
        asset, timeframe = key
        if key in self._subs:
            entry = self._subs[key]
            self._emit(
                {
                    "type": "subscribed",
                    "asset": asset,
                    "timeframe": timeframe,
                    "mode": entry["mode"],
                }
            )
            return

        entry: Dict[str, Any] = {
            "sub_id": None,
            "mode": "live",
            "since": time.time(),
            "live_seen": False,
            "last_live_at": None,
            "last_ts": 0,
            "poll_task": None,
            "monitor_task": None,
            "poll_busy": False,
        }
        self._subs[key] = entry

        async def on_candle(candle: Any, key: Key = key) -> None:
            current = self._subs.get(key)
            if current is None:
                return
            current["live_seen"] = True
            current["last_live_at"] = time.time()
            if current["mode"] == "poll":
                # O stream voltou a entregar -> cancela o fallback REST.
                self._set_mode(key, "live")
            current["last_ts"] = candle.timestamp
            self._emit(
                {
                    "type": "candle",
                    "asset": key[0],
                    "timeframe": key[1],
                    "candle": candle.model_dump(),
                    "mode": "live",
                }
            )

        stream_ok = False
        try:
            entry["sub_id"] = await self.adapter.subscribe_candles(
                asset, timeframe, on_candle
            )
            stream_ok = True
        except Exception as exc:  # noqa: BLE001 — BrokerError e demais
            print(
                f"[WS] stream indisponível para {asset} M{timeframe}: {exc!r}",
                flush=True,
            )
            entry["mode"] = "poll"

        self._emit(
            {
                "type": "subscribed",
                "asset": asset,
                "timeframe": timeframe,
                "mode": entry["mode"],
            }
        )
        if stream_ok:
            entry["monitor_task"] = asyncio.create_task(self._monitor_live(key))
        else:
            entry["poll_task"] = asyncio.create_task(self._poll_loop(key))

    async def _unsubscribe(self, key: Key) -> None:
        asset, timeframe = key
        entry = self._subs.pop(key, None)
        if entry is None:
            self._emit(
                {"type": "unsubscribed", "asset": asset, "timeframe": timeframe}
            )
            return
        for task_name in ("poll_task", "monitor_task"):
            task = entry.get(task_name)
            if task and not task.done():
                task.cancel()
        sub_id = entry.get("sub_id")
        if sub_id:
            try:
                await self.adapter.unsubscribe_candles(sub_id)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[WS] unsubscribe falhou ({asset} M{timeframe}): {exc!r}",
                    flush=True,
                )
        self._emit(
            {"type": "unsubscribed", "asset": asset, "timeframe": timeframe}
        )

    async def _cleanup_subs(self) -> None:
        for key in list(self._subs.keys()):
            try:
                await self._unsubscribe(key)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Modos live <-> poll
    # ------------------------------------------------------------------

    def _set_mode(self, key: Key, mode: str, reason: Optional[str] = None) -> None:
        entry = self._subs.get(key)
        if entry is None or entry["mode"] == mode:
            return
        if mode == "live":
            task = entry.get("poll_task")
            if task and not task.done():
                task.cancel()
            entry["poll_task"] = None
        else:
            task = entry.get("poll_task")
            if not task or task.done():
                entry["poll_task"] = asyncio.create_task(self._poll_loop(key))
        entry["mode"] = mode
        message: Dict[str, Any] = {
            "type": "status",
            "asset": key[0],
            "timeframe": key[1],
            "mode": mode,
        }
        if reason:
            message["reason"] = reason
        self._emit(message)

    async def _monitor_live(self, key: Key) -> None:
        """Vigia o stream: sem a 1ª vela no prazo, ou silêncio depois de
        funcionar, alterna para o fallback REST (poll)."""
        entry = self._subs.get(key)
        if entry is None:
            return
        while True:
            await asyncio.sleep(2.0)
            entry = self._subs.get(key)
            if entry is None:
                return
            if entry["mode"] != "live":
                continue
            now = time.time()
            if not entry["live_seen"]:
                if now - entry["since"] > self.LIVE_CONFIRM_SEC:
                    self._set_mode(
                        key,
                        "poll",
                        reason=(
                            f"sem dados do stream em "
                            f"{int(now - entry['since'])}s"
                        ),
                    )
            else:
                last = entry.get("last_live_at") or entry["since"]
                if now - last > self.LIVE_STALL_SEC:
                    self._set_mode(
                        key,
                        "poll",
                        reason=f"stream silenciou há {int(now - last)}s",
                    )

    async def _poll_loop(self, key: Key) -> None:
        """Fallback REST: busca a vela mais recente via get_candles."""
        asset, timeframe = key
        failures = 0
        try:
            while True:
                await asyncio.sleep(self.POLL_INTERVAL_SEC)
                entry = self._subs.get(key)
                if entry is None or entry["mode"] != "poll":
                    return
                if entry.get("poll_busy"):
                    continue
                entry["poll_busy"] = True
                try:
                    candles = await asyncio.wait_for(
                        self.adapter.get_candles(asset, timeframe, 3),
                        timeout=self.POLL_REQUEST_TIMEOUT_SEC,
                    )
                    if candles:
                        latest = max(candles, key=lambda c: c.timestamp)
                        if latest.timestamp and latest.timestamp != entry.get(
                            "last_ts"
                        ):
                            entry["last_ts"] = latest.timestamp
                            self._emit(
                                {
                                    "type": "candle",
                                    "asset": asset,
                                    "timeframe": timeframe,
                                    "candle": latest.model_dump(),
                                    "mode": "poll",
                                }
                            )
                    failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    if failures in (3, 15, 60):
                        print(
                            f"[WS] fallback REST {asset} M{timeframe} "
                            f"falhou ({failures}x): {exc!r}",
                            flush=True,
                        )
                    if failures == 5:
                        self._emit(
                            {
                                "type": "error",
                                "asset": asset,
                                "timeframe": timeframe,
                                "message": f"Sem dados: {exc}",
                            }
                        )
                    await asyncio.sleep(self.POLL_FAILURE_BACKOFF_SEC)
                finally:
                    entry["poll_busy"] = False
        except asyncio.CancelledError:
            pass
