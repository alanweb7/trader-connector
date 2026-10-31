"""
Testes offline do adapter ponte B3/MT5 — sem rede e sem terminal MT5.

Cobrem o mapeamento de timeframe, o parse de candles do REST, o consumo do
stream WS (candle_closed) e o escopo somente-dados (ordens/saldo).
"""
import asyncio
import json

import pytest

from src.adapters.mt5.mt5_adapter import MT5BridgeAdapter, timeframe_to_mt5
from src.core.errors import BrokerError, ErrorCodes, NotSupportedError
from src.core.models import Candle, OrderDirection, OrderRequest


# ---------------------------------------------------------------------------
# Fakes (formato httpx mínimo usado pelo adapter)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    """Stub do httpx.AsyncClient: devolve respostas pré-programadas."""

    def __init__(self, responses=None):
        self.is_closed = False
        self.responses = responses or {}
        self.calls = []

    async def request(self, method, path, params=None, timeout=None):
        self.calls.append({"method": method, "path": path, "params": params})
        handler = self.responses.get(path)
        if handler is None:
            return FakeResponse(404, {"detail": f"sem fake para {path}"})
        if callable(handler):
            return handler(params)
        return handler


HIST_PAYLOAD = {
    "symbol": "WINZ26",
    "timeframe": "M1",
    "timeframe_minutes": 1,
    "count": 2,
    "candles": [
        {
            "asset": "WINZ26",
            "timeframe": "M1",
            "timestamp": 1730000000,
            "open": 128450.0,
            "high": 128500.0,
            "low": 128400.0,
            "close": 128475.0,
            "volume": 1234.0,
        },
        {
            "asset": "WINZ26",
            "timeframe": "M1",
            "timestamp": 1730000060,
            "open": 128475.0,
            "high": 128510.0,
            "low": 128460.0,
            "close": 128490.0,
            "volume": 999.0,
        },
    ],
}


def make_adapter(responses=None):
    adapter = MT5BridgeAdapter()
    adapter._client = FakeClient(responses)
    adapter._connected = True
    return adapter


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mapeamento de timeframe
# ---------------------------------------------------------------------------


def test_timeframe_to_mt5_comum():
    assert timeframe_to_mt5(1) == "M1"
    assert timeframe_to_mt5(5) == "M5"
    assert timeframe_to_mt5(15) == "M15"
    assert timeframe_to_mt5(60) == "H1"
    assert timeframe_to_mt5(240) == "H4"
    assert timeframe_to_mt5(1440) == "D1"


def test_timeframe_to_mt5_invalido_lanca_not_supported():
    with pytest.raises(BrokerError) as exc:
        timeframe_to_mt5(7)
    assert exc.value.code == ErrorCodes.NOT_SUPPORTED


# ---------------------------------------------------------------------------
# Candles REST
# ---------------------------------------------------------------------------


def test_get_candles_parseia_payload_em_modelos_candle():
    adapter = make_adapter({"/api/v1/historical/WINZ26": FakeResponse(200, HIST_PAYLOAD)})
    candles = run(adapter.get_candles("winz26", 1, 2))

    assert len(candles) == 2
    assert all(isinstance(c, Candle) for c in candles)
    assert candles[0].asset == "WINZ26"
    assert candles[0].timeframe == "M1"
    assert candles[0].timestamp == 1730000000
    assert candles[0].close == 128475.0
    assert candles[0].volume == 1234.0
    # requisição enviou o nome MT5 e o símbolo normalizado
    call = adapter._client.calls[0]
    assert call["path"] == "/api/v1/historical/WINZ26"
    assert call["params"]["timeframe"] == "M1"
    assert call["params"]["count"] == 2


def test_get_candles_com_end_time_pagina():
    adapter = make_adapter({"/api/v1/historical/WINZ26": FakeResponse(200, HIST_PAYLOAD)})
    run(adapter.get_candles("WINZ26", 5, 2, end_time=1729999000))

    params = adapter._client.calls[0]["params"]
    assert params["timeframe"] == "M5"
    assert params["end_time"] == 1729999000


def test_get_candles_timeframe_nao_suportado():
    adapter = make_adapter()
    with pytest.raises(BrokerError) as exc:
        run(adapter.get_candles("WINZ26", 7, 10))
    assert exc.value.code == ErrorCodes.NOT_SUPPORTED
    assert adapter._client.calls == []  # nem bateu na API


def test_get_candles_404_vira_asset_not_found():
    adapter = make_adapter(
        {"/api/v1/historical/XXX": FakeResponse(404, {"detail": "Símbolo XXX não encontrado"})}
    )
    with pytest.raises(BrokerError) as exc:
        run(adapter.get_candles("XXX", 1, 10))
    assert exc.value.code == ErrorCodes.ASSET_NOT_FOUND
    assert "XXX" in str(exc.value)


# ---------------------------------------------------------------------------
# Stream WS (candle_closed -> callback)
# ---------------------------------------------------------------------------


def test_handle_ws_message_candle_closed_chama_callback():
    adapter = make_adapter()
    received = []

    def cb(candle):
        received.append(candle)

    msg = json.dumps(
        {
            "type": "candle_closed",
            "snapshot": False,
            "symbol": "WINZ26",
            "asset": "WINZ26",
            "timeframe": "M1",
            "timestamp": 1730000060,
            "open": 128475.0,
            "high": 128510.0,
            "low": 128460.0,
            "close": 128490.0,
            "volume": 999.0,
        }
    )
    run(adapter._handle_ws_message(msg, "WINZ26", "M1", cb))

    assert len(received) == 1
    candle = received[0]
    assert isinstance(candle, Candle)
    assert candle.asset == "WINZ26"
    assert candle.timeframe == "M1"
    assert candle.timestamp == 1730000060
    assert candle.close == 128490.0


def test_handle_ws_message_ignora_mensagens_nao_candle():
    adapter = make_adapter()
    received = []

    def cb(candle):
        received.append(candle)

    for payload in (
        {"type": "ready", "symbol": "WINZ26", "timeframe": "M1"},
        {"type": "ping"},
        {"type": "error", "message": "boom"},
        "nao-json",
    ):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        run(adapter._handle_ws_message(raw, "WINZ26", "M1", cb))

    assert received == []


def test_handle_ws_message_aceita_callback_async():
    adapter = make_adapter()
    received = []

    async def cb(candle):
        received.append(candle)

    msg = json.dumps(
        {"type": "candle_closed", "asset": "WDOZ26", "timeframe": "M5", "timestamp": 100}
    )
    run(adapter._handle_ws_message(msg, "WDOZ26", "M5", cb))
    assert len(received) == 1
    assert received[0].asset == "WDOZ26"
    assert received[0].timeframe == "M5"


# ---------------------------------------------------------------------------
# Catálogo curado B3 (WIN + BIT)
# ---------------------------------------------------------------------------

CATALOG_PAYLOAD = {
    "count": 2,
    "assets": [
        {
            "id": "WIN",
            "symbol": "WIN$",
            "name": "Mini Ibovespa (WINZ26)",
            "description": "IBOVESPA MINI - Por Liquidez (WINZ26) - Ajuste Proporcional",
            "contract": "WINZ26",
            "type": "cfd",
            "status": "open",
            "available": True,
            "digits": 0,
            "point": 1.0,
        },
        {
            "id": "BIT",
            "symbol": "BIT$",
            "name": "Bitcoin (BITX26)",
            "description": "Futuro de Bitcoin - Por Liquidez (BITX26) - Ajuste Proporcional",
            "contract": "BITX26",
            "type": "cfd",
            "status": "closed",
            "available": True,
            "digits": 2,
            "point": 0.01,
        },
    ],
}


def test_get_assets_usa_catalogo_curado_com_ids_estaveis():
    adapter = make_adapter({"/api/v1/catalog": FakeResponse(200, CATALOG_PAYLOAD)})
    assets = run(adapter.get_assets())

    assert [a.symbol for a in assets] == ["WIN", "BIT"]
    assert assets[0].name == "Mini Ibovespa (WINZ26)"
    assert assets[0].type == "cfd"
    assert assets[0].status == "open"
    assert assets[1].status == "closed"
    # não usa o catálogo cru do terminal
    assert [c["path"] for c in adapter._client.calls] == ["/api/v1/catalog"]


def test_get_assets_indisponivel_vira_unknown():
    payload = {
        "assets": [
            {
                "id": "WIN",
                "name": "Mini Ibovespa",
                "status": "open",
                "available": False,
            }
        ]
    }
    adapter = make_adapter({"/api/v1/catalog": FakeResponse(200, payload)})
    assets = run(adapter.get_assets())

    assert len(assets) == 1
    assert assets[0].status == "unknown"


def test_get_asset_resolve_por_id_estavel():
    adapter = make_adapter({"/api/v1/catalog": FakeResponse(200, CATALOG_PAYLOAD)})
    asset = run(adapter.get_asset("win"))

    assert asset.symbol == "WIN"
    assert asset.name == "Mini Ibovespa (WINZ26)"
    assert asset.status == "open"


def test_get_candles_preserva_id_estavel_do_catalogo():
    payload = {
        "symbol": "WIN$",
        "timeframe": "M1",
        "count": 1,
        "candles": [
            {
                "asset": "WIN$",
                "timeframe": "M1",
                "timestamp": 1730000000,
                "open": 170300.0,
                "high": 170400.0,
                "low": 170250.0,
                "close": 170350.0,
                "volume": 100.0,
            }
        ],
    }
    adapter = make_adapter({"/api/v1/historical/WIN": FakeResponse(200, payload)})
    candles = run(adapter.get_candles("WIN", 1, 1))

    # pede pelo id estável e devolve o id estável (o símbolo WIN$ é interno)
    assert adapter._client.calls[0]["path"] == "/api/v1/historical/WIN"
    assert candles[0].asset == "WIN"
    assert candles[0].close == 170350.0


def test_handle_ws_message_preserva_id_estavel():
    adapter = make_adapter()
    received = []
    msg = json.dumps(
        {
            "type": "candle_closed",
            "symbol": "WIN$",
            "asset": "WIN$",
            "timeframe": "M1",
            "timestamp": 1730000060,
            "open": 170300.0,
            "high": 170400.0,
            "low": 170250.0,
            "close": 170350.0,
            "volume": 99.0,
        }
    )
    run(adapter._handle_ws_message(msg, "WIN", "M1", received.append))

    assert len(received) == 1
    assert received[0].asset == "WIN"


# ---------------------------------------------------------------------------
# Escopo somente-dados
# ---------------------------------------------------------------------------


def test_ordens_nao_suportadas():
    adapter = make_adapter()
    order = OrderRequest(
        asset="WINZ26",
        direction=OrderDirection.CALL,
        amount=1.0,
        expiration=1,
    )
    for method in (
        adapter.place_order(order),
        adapter.cancel_order("x"),
        adapter.get_order("x"),
        adapter.get_order_result("x"),
    ):
        with pytest.raises(NotSupportedError):
            run(method)


def test_get_balance_nao_suportado():
    adapter = make_adapter()
    with pytest.raises(NotSupportedError):
        run(adapter.get_balance())


# ---------------------------------------------------------------------------
# Connect / status
# ---------------------------------------------------------------------------


def test_connect_ok_quando_health_mt5_connected():
    adapter = MT5BridgeAdapter()
    adapter._client = FakeClient(
        {"/health": FakeResponse(200, {"status": "ok", "mt5": {"connected": True, "login": 123}})}
    )
    result = run(adapter.connect({}))
    assert result["status"] == "connected"
    assert adapter._connected is True


def test_connect_falha_quando_mt5_desconectado():
    adapter = MT5BridgeAdapter()
    adapter._client = FakeClient(
        {"/health": FakeResponse(200, {"status": "degraded", "mt5": {"connected": False}})}
    )
    with pytest.raises(BrokerError) as exc:
        run(adapter.connect({}))
    assert exc.value.code == ErrorCodes.CONNECTION_FAILED
    assert adapter._connected is False


def test_subscribe_sem_conectar_lanca_erro():
    adapter = MT5BridgeAdapter()
    adapter._connected = False
    with pytest.raises(BrokerError):
        run(adapter.subscribe_candles("WINZ26", 1, lambda c: None))
