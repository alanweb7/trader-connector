"""
Repository for broker_connections table
Handles CRUD operations with encrypted credentials
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .client import get_supabase


class ConnectionRepository:
    """Repository for broker connection persistence"""

    def __init__(self):
        self._encryption_key: Optional[str] = None

    @property
    def encryption_key(self) -> str:
        """Get encryption key from environment"""
        if self._encryption_key is None:
            self._encryption_key = os.getenv(
                "BROKER_ENCRYPTION_KEY",
                "broker-gateway-default-key-change-in-production",
            )
        return self._encryption_key

    def create(
        self,
        name: str,
        broker: str,
        email: str,
        password: str,
        account_type: str = "practice",
        user_id: Optional[str] = None,
        server: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new broker connection
        
        Args:
            name: Connection display name
            broker: Broker identifier (e.g., 'iqoption')
            email: Broker login email (will be encrypted)
            password: Broker login password (will be encrypted)
            account_type: 'practice', 'real', or 'demo'
            user_id: Optional user ID for multi-tenant
            server: Optional server identifier
            
        Returns:
            Created connection record
        """
        db = get_supabase()
        
        connection_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        
        # Insert with raw credentials - the database trigger will encrypt them
        data = {
            "id": connection_id,
            "name": name,
            "broker": broker,
            "email_encrypted": email,
            "password_encrypted": password,
            "account_type": account_type,
            "status": "disconnected",
            "server": server,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        
        if user_id:
            data["user_id"] = user_id
        
        result = db.table("broker_connections").insert(data).execute()
        
        if result.data:
            return result.data[0]
        raise Exception("Failed to create connection")

    def _decrypt_email(self, email_encrypted: Optional[str]) -> str:
        """
        Decripta apenas o email (para exibição no card/modal de edição).
        Não decripta a senha — ela nunca deve sair do backend.
        """
        if not email_encrypted:
            return ""
        db = get_supabase()
        try:
            decrypted = db.rpc(
                "decrypt_broker_credentials",
                {
                    "p_email_encrypted": email_encrypted,
                    "p_password_encrypted": "",
                    "p_encryption_key": self.encryption_key,
                },
            ).execute()
            # Faz o downgrade da senha se a RPC tiver esse problema
            if decrypted.data:
                return decrypted.data[0].get("email", "") or ""
            return ""
        except Exception:
            return ""

    def get_by_id(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get connection by ID (safe fields + plain email for edit UI)

        Args:
            connection_id: Connection UUID

        Returns:
            Connection record (without password) or None
        """
        db = get_supabase()
        result = (
            db.table("broker_connections_safe")
            .select("*")
            .eq("id", connection_id)
            .execute()
        )
        if not result.data:
            return None
        record = result.data[0]
        raw = (
            db.table("broker_connections")
            .select("email_encrypted")
            .eq("id", connection_id)
            .single()
            .execute()
        )
        record["email"] = self._decrypt_email(raw.data.get("email_encrypted"))
        record.pop("email_encrypted", None)
        record.pop("password_encrypted", None)
        return record

    def get_with_credentials(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get connection with decrypted credentials (internal use only)
        
        Args:
            connection_id: Connection UUID
            
        Returns:
            Connection record with email/password or None
        """
        db = get_supabase()
        result = (
            db.table("broker_connections")
            .select("*")
            .eq("id", connection_id)
            .execute()
        )
        
        if not result.data:
            return None
        
        record = result.data[0]
        
        # Decrypt credentials using database function
        try:
            decrypted = db.rpc(
                "decrypt_broker_credentials",
                {
                    "p_email_encrypted": record.get("email_encrypted"),
                    "p_password_encrypted": record.get("password_encrypted"),
                    "p_encryption_key": self.encryption_key,
                },
            ).execute()
            
            if decrypted.data:
                record["email"] = decrypted.data[0].get("email", "")
                record["password"] = decrypted.data[0].get("password", "")
        except Exception:
            # Fallback: if decryption function doesn't exist, return as-is
            # This allows the app to work without the decrypt function
            record["email"] = record.get("email_encrypted", "")
            record["password"] = record.get("password_encrypted", "")
        
        # Remove raw encrypted fields
        record.pop("email_encrypted", None)
        record.pop("password_encrypted", None)
        
        return record

    def list_all(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all connections (safe fields + plain email for edit UI)

        Args:
            user_id: Optional user ID filter

        Returns:
            List of connection records (no password)
        """
        db = get_supabase()
        query = db.table("broker_connections_safe").select("*")

        if user_id:
            query = query.eq("user_id", user_id)

        result = query.order("created_at", desc=True).execute()
        records = result.data or []

        # Incluir email decriptado (nunca a senha)
        raws = (
            db.table("broker_connections")
            .select("id,email_encrypted")
            .execute()
        )
        raw_map = {r["id"]: r.get("email_encrypted") for r in (raws.data or [])}
        for record in records:
            record["email"] = self._decrypt_email(raw_map.get(record["id"]))
        return records

    def update_account_id(self, connection_id: str, account_id: str) -> None:
        """Persist the broker account id (e.g. IQ Option profile id)"""
        if not account_id:
            return
        db = get_supabase()
        db.table("broker_connections").update(
            {"account_id": str(account_id), "updated_at": datetime.utcnow().isoformat()}
        ).eq("id", connection_id).execute()

    def update_status(
        self,
        connection_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update connection status
        
        Args:
            connection_id: Connection UUID
            status: New status value
            error_message: Optional error message
            
        Returns:
            Updated connection record
        """
        db = get_supabase()
        
        update_data: Dict[str, Any] = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        if error_message is not None:
            update_data["error_message"] = error_message
        
        if status == "connected":
            update_data["last_heartbeat"] = datetime.utcnow().isoformat()
        
        result = (
            db.table("broker_connections")
            .update(update_data)
            .eq("id", connection_id)
            .execute()
        )
        
        return result.data[0] if result.data else None

    def update_heartbeat(self, connection_id: str) -> None:
        """Update last heartbeat timestamp"""
        db = get_supabase()
        db.table("broker_connections").update(
            {"last_heartbeat": datetime.utcnow().isoformat()}
        ).eq("id", connection_id).execute()

    def _update_fields(self, connection_id: str, fields: Dict[str, Any]) -> None:
        """
        Update specific fields directly (for credential updates)
        
        Args:
            connection_id: Connection UUID
            fields: Dictionary of fields to update
        """
        if not fields:
            return
            
        db = get_supabase()
        
        # Add updated_at timestamp
        fields["updated_at"] = datetime.utcnow().isoformat()
        
        db.table("broker_connections").update(fields).eq("id", connection_id).execute()

    def delete(self, connection_id: str) -> bool:
        """
        Delete a connection
        
        Args:
            connection_id: Connection UUID
            
        Returns:
            True if deleted
        """
        db = get_supabase()
        result = (
            db.table("broker_connections")
            .delete()
            .eq("id", connection_id)
            .execute()
        )
        return True

    def log_event(
        self,
        event_type: str,
        connection_id: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a broker event
        
        Args:
            event_type: Event type (e.g., 'connection.created')
            connection_id: Optional connection UUID
            event_data: Optional event payload
        """
        db = get_supabase()
        
        data = {
            "id": str(uuid4()),
            "event_type": event_type,
            "event_data": event_data or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        
        if connection_id:
            data["connection_id"] = connection_id
        
        db.table("broker_events").insert(data).execute()

    def save_order(
        self,
        connection_id: str,
        broker_order_id: Optional[str],
        asset: str,
        direction: str,
        amount: float,
        expiration: int = 1,
        status: str = "created",
    ) -> Dict[str, Any]:
        """
        Save an order to database
        
        Args:
            connection_id: Connection UUID
            broker_order_id: Order ID from broker
            asset: Asset symbol
            direction: 'CALL' or 'PUT'
            amount: Order amount
            expiration: Expiration in minutes
            status: Initial status
            
        Returns:
            Saved order record
        """
        db = get_supabase()
        
        order_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        
        data = {
            "id": order_id,
            "connection_id": connection_id,
            "broker_order_id": broker_order_id,
            "asset": asset,
            "direction": direction,
            "amount": amount,
            "expiration": expiration,
            "status": status,
            "created_at": now,
        }
        
        result = db.table("broker_orders").insert(data).execute()
        return result.data[0] if result.data else data

    def update_order(
        self,
        order_id: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
        profit: Optional[float] = None,
        payout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update order status/result
        
        Args:
            order_id: Order UUID
            status: New status
            result: 'WIN', 'LOSS', or 'DRAW'
            profit: Profit amount
            payout: Payout percentage
            
        Returns:
            Updated order record
        """
        db = get_supabase()
        
        update_data: Dict[str, Any] = {}
        
        if status is not None:
            update_data["status"] = status
        if result is not None:
            update_data["result"] = result
        if profit is not None:
            update_data["profit"] = profit
        if payout is not None:
            update_data["payout"] = payout
        
        if status == "closed":
            update_data["closed_at"] = datetime.utcnow().isoformat()
        
        if not update_data:
            return None
        
        result_query = (
            db.table("broker_orders")
            .update(update_data)
            .eq("id", order_id)
            .execute()
        )
        
        return result_query.data[0] if result_query.data else None


# Singleton instance
connection_repository = ConnectionRepository()
