"""
Testes offline da sessão WebSocket de candles e do mapeamento de payload
candle-generated — sem rede e sem sessão IQ.
"""
import asyncio
import json

from fastapi import WebSocketDisconnect

from src.adapters.iqoption.iqoption_adapter import IQOptionAdapter
from src.core.errors import BrokerError, ErrorCodes
from src.core.models import Candle
from src.transport.websocket.candle_stream import CandleStreamSession


class FakeWS:
    """WebSocket fake no formato usado pela sessão (starlette)."""

    def __init__(self):
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.sent = []

    async def receive_text(self):
        item = await self.incoming.get()
        if item is None:
            raise WebSocketDisconnect(code=1000)
        return item

    async def send_json(self, message):
        self.sent.append(message)

    def feed(self, message):
        self.incoming.put_nowait(
            json.dumps(message) if isinstance(message, dict) else message
        )

    def close(self):
        self.incoming.put_nowait(None)

    def messages(self, mtype=None):
        return [m for m in self.sent if mtype is None or m.get("type") == mtype]


class FakeAdapter:
    """Adapter fake: subscribe guarda o callback ou falha; get_candles devolve lista."""

    def __init__(self, fail_subscribe=False, candles=None):
        self.fail_subscribe = fail_subscribe
        self.candles = candles if candles is not None else []
        self.callbacks = {}
        self.unsubscribed = []
        self.get_candles_calls = 0
        self._count = 0

    async def subscribe_candles(self, asset, timeframe, callback):
        if self.fail_subscribe:
            raise BrokerError(
                "stream indisponivel",
                code=ErrorCodes.NOT_SUPPORTED,
                broker="iqoption",
            )
        self._count += 1
        sub_id = f"sub-{self._count}"
        self.callbacks[(asset, timeframe)] = callback
        return sub_id

    async def unsubscribe_candles(self, subscription_id):
        self.unsubscribed.append(subscription_id)

    async def get_candles(self, asset, timeframe, count):
        self.get_candles_calls += 1
        return list(self.candles)


def make_candle(ts=1000, close=1.5):
    return Candle(
        asset="TEST",
        timeframe="M1",
        timestamp=ts,
        open=1.0,
        high=1.6,
        low=0.9,
        close=close,
        volume=0.0,
    )


async def wait_for(predicate, timeout=3.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


async def start_session(adapter, **attrs):
    ws = FakeWS()
    session = CandleStreamSession(ws, "conn-1", adapter)
    for key, value in attrs.items():
        setattr(session, key, value)
    task = asyncio.create_task(session.run())
    return ws, session, task


async def finish(ws, task):
    ws.close()
    await asyncio.wait_for(task, 5)


async def test_subscribe_delivers_live_candles():
    adapter = FakeAdapter()
    ws, session, task = await start_session(adapter)
    try:
        ws.feed({"action": "subscribe", "asset": "EURUSD-OTC", "timeframe": 1})
        assert await wait_for(lambda: ws.messages("subscribed"))
        assert ws.messages("subscribed")[0]["mode"] == "live"

        callback = adapter.callbacks[("EURUSD-OTC", 1)]
        await callback(make_candle(ts=1000, close=1.1))
        assert await wait_for(lambda: ws.messages("candle"))
        message = ws.messages("candle")[0]
        assert message["mode"] == "live"
        assert message["candle"]["timestamp"] == 1000
        assert message["candle"]["close"] == 1.1

        ws.feed({"action": "unsubscribe", "asset": "EURUSD-OTC", "timeframe": 1})
        assert await wait_for(lambda: ws.messages("unsubscribed"))
        assert adapter.unsubscribed == ["sub-1"]
    finally:
        await finish(ws, task)


async def test_subscribe_failure_falls_back_to_poll():
    adapter = FakeAdapter(fail_subscribe=True, candles=[make_candle(ts=2000)])
    ws, session, task = await start_session(adapter, POLL_INTERVAL_SEC=0.05)
    try:
        ws.feed({"action": "subscribe", "asset": "EURUSD-OTC", "timeframe": 1})
        assert await wait_for(lambda: ws.messages("subscribed"))
        assert ws.messages("subscribed")[0]["mode"] == "poll"

        assert await wait_for(lambda: ws.messages("candle"))
        message = ws.messages("candle")[0]
        assert message["mode"] == "poll"
        assert message["candle"]["timestamp"] == 2000

        # dedupe: a mesma vela não é reenviada
        sent = len(ws.messages("candle"))
        await asyncio.sleep(0.3)
        assert len(ws.messages("candle")) == sent
        assert adapter.get_candles_calls >= 2
    finally:
        await finish(ws, task)


async def test_monitor_switches_to_poll_when_stream_silent():
    adapter = FakeAdapter(candles=[make_candle(ts=3000)])
    ws, session, task = await start_session(
        adapter, LIVE_CONFIRM_SEC=0.3, POLL_INTERVAL_SEC=0.05
    )
    try:
        ws.feed({"action": "subscribe", "asset": "EURUSD-OTC", "timeframe": 1})
        assert await wait_for(lambda: ws.messages("subscribed"))
        assert ws.messages("subscribed")[0]["mode"] == "live"

        # sem nenhuma vela "live" -> monitor deve alternar para poll
        assert await wait_for(
            lambda: any(m.get("mode") == "poll" for m in ws.messages("status")),
            timeout=4.0,
        )
        assert await wait_for(lambda: ws.messages("candle"))
        assert ws.messages("candle")[0]["mode"] == "poll"
        # fallback continua ativo (mais de uma tentativa de get_candles)
        assert adapter.get_candles_calls >= 1
    finally:
        await finish(ws, task)


async def test_live_candle_returns_from_poll_to_live():
    adapter = FakeAdapter(candles=[make_candle(ts=4000)])
    ws, session, task = await start_session(
        adapter, LIVE_CONFIRM_SEC=0.3, POLL_INTERVAL_SEC=0.05
    )
    try:
        ws.feed({"action": "subscribe", "asset": "EURUSD-OTC", "timeframe": 1})
        assert await wait_for(lambda: ws.messages("subscribed"))

        # stream cala -> monitor alterna para poll
        assert await wait_for(
            lambda: any(m.get("mode") == "poll" for m in ws.messages("status")),
            timeout=4.0,
        )

        # callback do adapter entrega vela -> deve voltar para live
        callback = adapter.callbacks[("EURUSD-OTC", 1)]
        await callback(make_candle(ts=4100, close=1.2))
        assert await wait_for(
            lambda: any(m.get("mode") == "live" for m in ws.messages("status"))
        )
        assert await wait_for(lambda: ws.messages("candle"))
        live_candles = [m for m in ws.messages("candle") if m["mode"] == "live"]
        assert live_candles
        assert live_candles[-1]["candle"]["timestamp"] == 4100
    finally:
        await finish(ws, task)


async def test_ping_invalid_messages():
    adapter = FakeAdapter()
    ws, session, task = await start_session(adapter)
    try:
        ws.feed({"action": "ping"})
        assert await wait_for(lambda: ws.messages("pong"))

        ws.feed({"acao": "errada"})
        assert await wait_for(lambda: ws.messages("error"))

        ws.feed("nao é json")
        assert await wait_for(lambda: len(ws.messages("error")) >= 2)

        ws.feed({"action": "subscribe", "asset": "", "timeframe": 0})
        assert await wait_for(lambda: len(ws.messages("error")) >= 3)
    finally:
        await finish(ws, task)


def test_msg_to_candle_mapping_and_fallbacks():
    adapter = IQOptionAdapter()
    # payload com max/min/close (formato do histórico IQ)
    candle = adapter._msg_to_candle(
        "EURUSD-OTC",
        1,
        {
            "from": 1791352920,
            "open": 1.1017,
            "max": 1.1025,
            "min": 1.1016,
            "close": 1.1024,
            "volume": 0.0,
        },
    )
    assert candle is not None
    assert candle.timestamp == 1791352920
    assert candle.high == 1.1025
    assert candle.low == 1.1016
    assert candle.close == 1.1024
    assert candle.timeframe == "M1"

    # payload com value/high/low (formato candles-generated)
    candle2 = adapter._msg_to_candle(
        "TEST", 5, {"from": 100, "value": 2.5, "high": 2.7, "low": 2.3}
    )
    assert candle2 is not None
    assert candle2.close == 2.5
    assert candle2.high == 2.7
    assert candle2.low == 2.3
    assert candle2.timeframe == "M5"

    # sem close/value -> descarta
    assert adapter._msg_to_candle("TEST", 1, {"from": 1}) is None
