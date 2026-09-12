"""
Gerenciador de eventos centralizado
"""
import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class EventManager:
    """Gerenciador de eventos centralizado"""

    def __init__(self, max_history: int = 1000):
        self._handlers: Dict[str, List[Callable]] = {}
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history

    def on(self, event_name: str, handler: Callable) -> str:
        """
        Registra um handler para um evento
        
        Args:
            event_name: Nome do evento
            handler: Função a ser chamada
            
        Returns:
            ID do handler para remoção
        """
        handler_id = str(uuid4())
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append({"id": handler_id, "handler": handler})
        return handler_id

    def off(self, event_name: str, handler_id: str) -> bool:
        """
        Remove um handler de um evento
        
        Args:
            event_name: Nome do evento
            handler_id: ID do handler
            
        Returns:
            True se removido, False caso contrário
        """
        if event_name in self._handlers:
            self._handlers[event_name] = [
                h for h in self._handlers[event_name] if h["id"] != handler_id
            ]
            return True
        return False

    async def emit(self, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Emite um evento
        
        Args:
            event_name: Nome do evento
            data: Dados do evento
        """
        event = {
            "event": event_name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data or {},
        }

        # Adicionar ao histórico
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Chamar handlers
        if event_name in self._handlers:
            for handler_info in self._handlers[event_name]:
                try:
                    result = handler_info["handler"](event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"[EventManager] Error in handler for {event_name}: {e}")

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Obtém histórico de eventos
        
        Args:
            limit: Limite de eventos
            
        Returns:
            Histórico de eventos
        """
        return self._history[-limit:]

    def clear_history(self) -> None:
        """Limpa histórico de eventos"""
        self._history.clear()


# Instância singleton
event_manager = EventManager()