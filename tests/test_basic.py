"""
Testes básicos para o Broker Gateway
"""
import pytest
from src.core.models import (
    Account,
    AccountType,
    Asset,
    AssetType,
    Balance,
    Candle,
    Connection,
    ConnectionStatus,
    OrderDirection,
    OrderRequest,
    OrderResponse,
    OrderResult,
    OrderStatus,
)
from src.core.errors import BrokerError, ErrorCodes
from src.core.events.event_manager import EventManager
from src.core.registry.broker_registry import BrokerRegistry
from src.adapters.iqoption import IQOptionAdapter


class TestModels:
    """Testes para modelos"""

    def test_account_creation(self):
        account = Account(
            id="123",
            broker="iqoption",
            type=AccountType.PRACTICE,
            currency="USD",
        )
        assert account.broker == "iqoption"
        assert account.type == AccountType.PRACTICE.value

    def test_balance_creation(self):
        balance = Balance(available=100.0, currency="USD")
        assert balance.available == 100.0

    def test_asset_creation(self):
        asset = Asset(symbol="EURUSD", name="EUR/USD", type=AssetType.BINARY)
        assert asset.symbol == "EURUSD"
        assert asset.payout == 0.0

    def test_candle_creation(self):
        candle = Candle(
            asset="EURUSD",
            timeframe="M1",
            timestamp=1757650000,
            open=1.1742,
            high=1.1748,
            low=1.1739,
            close=1.1746,
        )
        assert candle.asset == "EURUSD"
        assert candle.open == 1.1742

    def test_order_request(self):
        order = OrderRequest(
            asset="EURUSD",
            direction=OrderDirection.CALL,
            amount=10.0,
            expiration=1,
        )
        assert order.asset == "EURUSD"
        assert order.direction == OrderDirection.CALL.value
        assert order.idempotency_key is not None

    def test_connection(self):
        connection = Connection(
            broker="iqoption",
            account_type=AccountType.PRACTICE,
        )
        assert connection.broker == "iqoption"
        assert connection.status == ConnectionStatus.DISCONNECTED.value


class TestErrors:
    """Testes para erros"""

    def test_broker_error(self):
        error = BrokerError(
            "Test error",
            code=ErrorCodes.CONNECTION_FAILED,
            broker="iqoption",
        )
        assert error.message == "Test error"
        assert error.code == ErrorCodes.CONNECTION_FAILED
        assert error.broker == "iqoption"

    def test_error_to_dict(self):
        error = BrokerError(
            "Test error",
            code=ErrorCodes.TIMEOUT,
        )
        error_dict = error.to_dict()
        assert error_dict["message"] == "Test error"
        assert error_dict["code"] == "TIMEOUT"


class TestEventManager:
    """Testes para gerenciador de eventos"""

    def test_event_emission(self):
        manager = EventManager()
        received_events = []

        def handler(event):
            received_events.append(event)

        manager.on("test.event", handler)
        manager.emit("test.event", {"key": "value"})

        assert len(received_events) == 1
        assert received_events[0]["event"] == "test.event"

    def test_event_history(self):
        manager = EventManager()
        manager.emit("event1", {})
        manager.emit("event2", {})

        history = manager.get_history()
        assert len(history) == 2

    def test_clear_history(self):
        manager = EventManager()
        manager.emit("event1", {})
        manager.clear_history()

        history = manager.get_history()
        assert len(history) == 0


class TestBrokerRegistry:
    """Testes para registro de brokers"""

    def test_register_adapter(self):
        registry = BrokerRegistry()
        adapter = IQOptionAdapter()
        registry.register("iqoption", adapter)

        assert registry.has("iqoption")
        assert registry.get("iqoption") is adapter

    def test_list_brokers(self):
        registry = BrokerRegistry()
        registry.register("iqoption", IQOptionAdapter())

        brokers = registry.list_brokers()
        assert "iqoption" in brokers

    def test_duplicate_registration(self):
        registry = BrokerRegistry()
        registry.register("iqoption", IQOptionAdapter())

        with pytest.raises(ValueError):
            registry.register("iqoption", IQOptionAdapter())

    def test_connection_management(self):
        registry = BrokerRegistry()
        connection = Connection(broker="iqoption")

        registry.register_connection(str(connection.id), connection)
        assert registry.get_connection(str(connection.id)) is connection

        registry.remove_connection(str(connection.id))
        assert registry.get_connection(str(connection.id)) is None


class TestIQOptionAdapter:
    """Testes para adapter IQ Option"""

    def test_adapter_initialization(self):
        adapter = IQOptionAdapter()
        assert adapter._api is None
        assert adapter._connected is False

    def test_not_connected_error(self):
        adapter = IQOptionAdapter()
        with pytest.raises(BrokerError) as exc_info:
            adapter._ensure_connected()
        assert exc_info.value.code == ErrorCodes.CONNECTION_FAILED