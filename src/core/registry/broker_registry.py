"""
Registro central de adapters de broker
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from ..interfaces.broker_adapter import BrokerAdapter
from ..models import Connection


class BrokerRegistry:
    """Registro central de adapters de broker"""

    def __init__(self):
        self._adapters: Dict[str, BrokerAdapter] = {}
        self._connections: Dict[str, Connection] = {}
        self._connection_adapters: Dict[str, BrokerAdapter] = {}

    def register(self, name: str, adapter: BrokerAdapter) -> None:
        """
        Registra um adapter de broker (template compartilhado para auto-reconnect).

        Args:
            name: Nome do broker
            adapter: Instância do adapter
        """
        if name in self._adapters:
            raise ValueError(f"Adapter {name} already registered")
        self._adapters[name] = adapter
        print(f"[BrokerRegistry] Adapter {name} registered")

    def get(self, name: str) -> BrokerAdapter:
        """
        Obtém o adapter-template por nome.

        Args:
            name: Nome do broker

        Returns:
            Adapter-template
        """
        if name not in self._adapters:
            raise ValueError(f"Adapter {name} not found")
        return self._adapters[name]

    def list_brokers(self) -> List[str]:
        """
        Lista todos os brokers registrados

        Returns:
            Lista de nomes de brokers
        """
        return list(self._adapters.keys())

    def has(self, name: str) -> bool:
        """
        Verifica se um broker está registrado

        Args:
            name: Nome do broker

        Returns:
            True se registrado
        """
        return name in self._adapters

    def _create_adapter_instance(self, broker_name: str) -> BrokerAdapter:
        """Cria uma NOVA instância do adapter para isolar sessão por conexão."""
        template = self.get(broker_name)
        cls = type(template)
        instance = cls.__new__(cls)
        cls.__init__(instance)
        return instance

    def register_connection(self, connection_id: str, connection: Connection) -> None:
        """
        Registra uma conexão com seu PRÓPRIO adapter (sessão isolada).

        Args:
            connection_id: ID da conexão
            connection: Dados da conexão
        """
        self._connections[connection_id] = connection
        if connection_id not in self._connection_adapters:
            self._connection_adapters[connection_id] = self._create_adapter_instance(connection.broker)
            print(f"[BrokerRegistry] Adapter instance criado para {connection_id}")

    def get_connection(self, connection_id: str) -> Optional[Connection]:
        """
        Obtém uma conexão

        Args:
            connection_id: ID da conexão

        Returns:
            Conexão ou None
        """
        return self._connections.get(connection_id)

    def remove_connection(self, connection_id: str) -> bool:
        """
        Remove uma conexão e seu adapter dedicado.

        Args:
            connection_id: ID da conexão

        Returns:
            True se removido
        """
        removed = False
        if connection_id in self._connections:
            del self._connections[connection_id]
            removed = True
        if connection_id in self._connection_adapters:
            del self._connection_adapters[connection_id]
        return removed

    def list_connections(self) -> List[Connection]:
        """
        Lista todas as conexões

        Returns:
            Lista de conexões
        """
        return list(self._connections.values())

    def get_adapter_for_connection(self, connection_id: str) -> Optional[BrokerAdapter]:
        """
        Obtém o adapter DEDICADO para uma conexão (sessão isolada).

        Args:
            connection_id: ID da conexão

        Returns:
            Adapter dedicado da conexão ou None
        """
        if connection_id in self._connection_adapters:
            return self._connection_adapters[connection_id]
        connection = self.get_connection(connection_id)
        if connection and connection.broker in self._adapters:
            self._connection_adapters[connection_id] = self._create_adapter_instance(connection.broker)
            return self._connection_adapters[connection_id]
        return None


# Instância singleton
broker_registry = BrokerRegistry()