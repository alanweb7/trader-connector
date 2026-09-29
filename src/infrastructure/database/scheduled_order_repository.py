"""
Repository for broker_scheduled_orders table
Agendamento de ordens (worker dispara em scheduled_for).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .client import get_supabase

TABLE = "broker_scheduled_orders"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScheduledOrderRepository:
    """Repository para ordens agendadas"""

    def create(
        self,
        connection_id: str,
        asset: str,
        direction: str,
        amount: float,
        expiration: int,
        scheduled_for: str,
        mode: str = "next_candle",
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria uma ordem agendada.

        Args:
            connection_id: Conexão da corretora
            asset: Símbolo do ativo (ex: EURUSD-OTC)
            direction: CALL ou PUT
            amount: Valor apostado
            expiration: Expiração em minutos
            scheduled_for: ISO UTC quando disparar
            mode: next_candle | fixed_time
            timeframe: Timeframe usado no next_candle (ex: 1m, 5m)

        Returns:
            Registro criado
        """
        db = get_supabase()
        now = _utcnow_iso()
        data = {
            "id": str(uuid4()),
            "connection_id": connection_id,
            "asset": asset,
            "direction": direction,
            "amount": amount,
            "expiration": expiration,
            "mode": mode,
            "timeframe": timeframe,
            "scheduled_for": scheduled_for,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        result = db.table(TABLE).insert(data).execute()
        if result.data:
            return result.data[0]
        raise Exception("Failed to create scheduled order")

    def list(
        self,
        connection_id: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Lista ordens agendadas (mais recentes primeiro)."""
        db = get_supabase()
        query = db.table(TABLE).select("*")
        if connection_id:
            query = query.eq("connection_id", connection_id)
        if statuses:
            query = query.in_("status", statuses)
        result = query.order("scheduled_for", desc=False).limit(limit).execute()
        return result.data or []

    def list_pending_due(self, lookahead_iso: str) -> List[Dict[str, Any]]:
        """
        Pendentes com scheduled_for até lookahead_iso (para o worker sincronizar).
        """
        db = get_supabase()
        result = (
            db.table(TABLE)
            .select("*")
            .eq("status", "pending")
            .lte("scheduled_for", lookahead_iso)
            .order("scheduled_for", desc=False)
            .limit(100)
            .execute()
        )
        return result.data or []

    def claim(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Claim atômico: pending → firing. Retorna None se outra instância
        já reivindicou (UPDATE ... WHERE status='pending' é atômico no PG).
        """
        db = get_supabase()
        result = (
            db.table(TABLE)
            .update({"status": "firing", "updated_at": _utcnow_iso()})
            .eq("id", order_id)
            .eq("status", "pending")
            .execute()
        )
        if result.data:
            return result.data[0]
        return None

    def finish(
        self,
        order_id: str,
        status: str,
        broker_order_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Finaliza uma ordem agendada (fired/rejected/failed/missed/cancelled)."""
        db = get_supabase()
        data: Dict[str, Any] = {"status": status, "updated_at": _utcnow_iso()}
        if status in ("fired", "rejected", "failed", "missed"):
            data["fired_at"] = _utcnow_iso()
        if broker_order_id is not None:
            data["broker_order_id"] = broker_order_id
        if error is not None:
            data["error"] = error
        result = (
            db.table(TABLE)
            .update(data)
            .eq("id", order_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None

    def get_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma ordem agendada por id."""
        db = get_supabase()
        result = (
            db.table(TABLE).select("*").eq("id", order_id).limit(1).execute()
        )
        if result.data:
            return result.data[0]
        return None

    def cancel(self, order_id: str) -> bool:
        """Cancela apenas se ainda pending (atômico)."""
        db = get_supabase()
        result = (
            db.table(TABLE)
            .update({"status": "cancelled", "updated_at": _utcnow_iso()})
            .eq("id", order_id)
            .eq("status", "pending")
            .execute()
        )
        return bool(result.data)

    def fail_firing(self, error: str) -> int:
        """
        Linhas presas em 'firing' (crash/restart no meio do disparo) → failed.
        Nunca re-dispara sozinhas.
        """
        db = get_supabase()
        result = (
            db.table(TABLE)
            .update(
                {
                    "status": "failed",
                    "error": error,
                    "updated_at": _utcnow_iso(),
                }
            )
            .eq("status", "firing")
            .execute()
        )
        return len(result.data or [])


# Singleton instance
scheduled_order_repository = ScheduledOrderRepository()
