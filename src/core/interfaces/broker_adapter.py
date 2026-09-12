"""
Interface padrão para adapters de broker
Cada broker deve implementar esta interface
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from ..models import Account, Balance, Asset, Candle, OrderRequest, OrderResponse, OrderResult


class BrokerAdapter(ABC):
    """Interface abstrata para adapters de broker"""

    @abstractmethod
    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Conecta ao broker
        
        Args:
            config: Configuração da conexão (email, password, etc)
            
        Returns:
            Status da conexão
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Desconecta do broker"""
        pass

    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """
        Obtém status da conexão
        
        Returns:
            Status atual da conexão
        """
        pass

    @abstractmethod
    async def get_account(self) -> Account:
        """
        Obtém informações da conta
        
        Returns:
            Dados da conta
        """
        pass

    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        Obtém saldo da conta
        
        Returns:
            Saldo atual
        """
        pass

    @abstractmethod
    async def get_assets(self) -> List[Asset]:
        """
        Lista ativos disponíveis
        
        Returns:
            Lista de ativos
        """
        pass

    @abstractmethod
    async def get_asset(self, symbol: str) -> Asset:
        """
        Obtém informações de um ativo específico
        
        Args:
            symbol: Símbolo do ativo
            
        Returns:
            Dados do ativo
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def unsubscribe_candles(self, subscription_id: str) -> None:
        """
        Cancela inscrição de candles
        
        Args:
            subscription_id: ID da inscrição
        """
        pass

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Envia ordem
        
        Args:
            order: Dados da ordem
            
        Returns:
            Resposta da ordem
        """
        pass

    @abstractmethod
    async def get_order(self, order_id: str) -> OrderResponse:
        """
        Obtém status de uma ordem
        
        Args:
            order_id: ID da ordem
            
        Returns:
            Dados da ordem
        """
        pass

    @abstractmethod
    async def get_order_result(self, order_id: str) -> OrderResult:
        """
        Obtém resultado de uma ordem
        
        Args:
            order_id: ID da ordem
            
        Returns:
            Resultado da ordem
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        """
        Cancela uma ordem
        
        Args:
            order_id: ID da ordem
        """
        pass