"""
Servidor principal do Broker Gateway
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core.models import Connection, ConnectionStatus, BrokerConfig, Account, Balance
from .core.registry.broker_registry import broker_registry
from .core.events.event_manager import event_manager
from .core.errors import BrokerError
from .adapters.iqoption import IQOptionAdapter
from .infrastructure.database.connection_repository import connection_repository
from .infrastructure.database.scheduled_order_repository import scheduled_order_repository

# Carregar variáveis de ambiente
load_dotenv()


# Modelos para request/response
class ConnectRequest(BaseModel):
    email: str
    password: str
    account_type: str = "practice"
    name: Optional[str] = None
    user_id: Optional[str] = None


class UpdateConnectionRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    account_type: Optional[str] = None
    name: Optional[str] = None


class ConnectionResponse(BaseModel):
    id: str
    broker: str
    account_type: str
    status: str
    name: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: dict = {}


# Lifespan context manager
async def _auto_reconnect_connection(connection_id: str, max_attempts: int = 3) -> None:
    """Reconecta automaticamente uma connection que estava ativa antes do restart."""
    for attempt in range(1, max_attempts + 1):
        try:
            connection = broker_registry.get_connection(connection_id)
            if not connection:
                return
            adapter = broker_registry.get_adapter_for_connection(connection_id)
            if not adapter:
                return
            db_conn = connection_repository.get_with_credentials(connection_id)
            if not db_conn or not db_conn.get("password"):
                return

            connection.status = ConnectionStatus.CONNECTING
            connection_repository.update_status(connection_id, "connecting")
            result = await adapter.connect({
                "email": db_conn.get("email", ""),
                "password": db_conn.get("password", ""),
                "account_type": connection.account_type.value if hasattr(connection.account_type, "value") else connection.account_type,
            })
            connection.status = ConnectionStatus(result["status"])
            connection_repository.update_status(connection_id, result["status"])
            connection_repository.log_event(
                "connection.reconnected",
                connection_id=connection_id,
                event_data={"status": result["status"], "auto": True},
            )
            print(f"[BrokerGateway] auto-reconnect OK: {connection_id}", flush=True)
            return
        except Exception as e:
            print(
                f"[BrokerGateway] auto-reconnect {connection_id} "
                f"tentativa {attempt}/{max_attempts} falhou: {e}",
                flush=True,
            )
            conn = broker_registry.get_connection(connection_id)
            if conn:
                conn.status = ConnectionStatus.ERROR
            try:
                connection_repository.update_status(connection_id, "error", str(e))
            except Exception:
                pass
            if attempt < max_attempts:
                await asyncio.sleep(5 * attempt)


# ---------------------------------------------------------------------------
# Worker de ordens agendadas (abertura em horário fixo / próxima vela)
# ---------------------------------------------------------------------------
# Máximo de atraso aceito após scheduled_for — além disso marca 'missed'.
SCHEDULED_GRACE_SEC = float(os.getenv("SCHEDULED_GRACE_SEC", "20"))
# Intervalo de sincronização com o banco (novas linhas pending).
SCHEDULED_POLL_SEC = float(os.getenv("SCHEDULED_POLL_SEC", "1.0"))

_scheduled_tasks: "dict[str, asyncio.Task]" = {}


async def _fire_scheduled_order(row: dict) -> None:
    """
    Espera até scheduled_for, reivindica a linha (claim atômico) e dispara
    a ordem pelo mesmo caminho do endpoint manual (/connections/{id}/orders).
    """
    from .core.models import OrderRequest, OrderDirection, AccountType

    order_id = row["id"]
    try:
        scheduled_for = datetime.fromisoformat(
            str(row["scheduled_for"]).replace("Z", "+00:00")
        )
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

        delay = (scheduled_for - datetime.now(timezone.utc)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

        # Claim atômico: só uma instância do worker dispara (pending → firing).
        claimed = scheduled_order_repository.claim(order_id)
        if not claimed:
            return  # cancelada por usuário ou outra instância reivindicou

        lateness = (datetime.now(timezone.utc) - scheduled_for).total_seconds()
        if lateness > SCHEDULED_GRACE_SEC:
            scheduled_order_repository.finish(
                order_id,
                "missed",
                error=f"disparo atrasado {lateness:.1f}s > {SCHEDULED_GRACE_SEC:.0f}s (worker parado?)",
            )
            print(
                f"[Scheduled] order {order_id} MISSED (atraso {lateness:.1f}s)",
                flush=True,
            )
            return

        connection = broker_registry.get_connection(row["connection_id"])
        adapter = broker_registry.get_adapter_for_connection(row["connection_id"])
        if not connection or not adapter:
            scheduled_order_repository.finish(
                order_id, "failed", error="conexão/adapter indisponível"
            )
            return

        acct = connection.account_type
        order_request = OrderRequest(
            asset=row["asset"],
            direction=OrderDirection(row["direction"].upper()),
            amount=float(row["amount"]),
            expiration=int(row.get("expiration") or 1),
            account_type=AccountType(acct.value if hasattr(acct, "value") else acct),
            connection_id=row["connection_id"],
        )

        db_order = connection_repository.save_order(
            connection_id=row["connection_id"],
            broker_order_id=None,
            asset=order_request.asset,
            direction=(
                order_request.direction.value
                if hasattr(order_request.direction, "value")
                else str(order_request.direction)
            ),
            amount=order_request.amount,
            expiration=order_request.expiration,
            status="pending",
        )

        try:
            result = await adapter.place_order(order_request)
            final_status = (
                result.status.value
                if hasattr(result.status, "value")
                else str(result.status)
            )
            connection_repository.update_order(
                order_id=db_order["id"],
                status=final_status,
                broker_order_id=result.id,
            )
            connection_repository.log_event(
                "order.scheduled_fired" if result.id else "order.scheduled_rejected",
                connection_id=row["connection_id"],
                event_data={
                    "scheduled_order_id": order_id,
                    "order_id": db_order["id"],
                    "asset": order_request.asset,
                    "status": final_status,
                    "error": result.error,
                },
            )
            if result.id and final_status == "accepted":
                scheduled_order_repository.finish(
                    order_id, "fired", broker_order_id=str(result.id)
                )
                dir_label = (
                    order_request.direction.value
                    if hasattr(order_request.direction, "value")
                    else str(order_request.direction)
                )
                print(
                    f"[Scheduled] order {order_id} FIRED -> broker {result.id} "
                    f"({order_request.asset} {dir_label})",
                    flush=True,
                )
            else:
                scheduled_order_repository.finish(
                    order_id, "rejected", error=result.error or "rejeitada pela corretora"
                )
                print(
                    f"[Scheduled] order {order_id} REJECTED: {result.error}",
                    flush=True,
                )
        except BrokerError as e:
            connection_repository.update_order(
                order_id=db_order["id"], status="rejected"
            )
            scheduled_order_repository.finish(order_id, "rejected", error=str(e))
            print(f"[Scheduled] order {order_id} REJECTED: {e}", flush=True)

    except asyncio.CancelledError:
        # Shutdown no meio do caminho: não deixar linha presa em 'firing'.
        try:
            scheduled_order_repository.finish(
                order_id, "failed", error="worker reiniciado durante o disparo"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            scheduled_order_repository.finish(order_id, "failed", error=str(e))
        except Exception:
            pass
        print(f"[Scheduled] order {order_id} FAILED: {e}", flush=True)


async def _scheduled_orders_worker() -> None:
    """
    Task periódica: sincroniza pending do banco e mantém uma task de disparo
    por ordem (sleep até scheduled_for com precisão de ms).
    """
    print(
        f"[BrokerGateway] scheduled-orders worker iniciado "
        f"(poll={SCHEDULED_POLL_SEC}s grace={SCHEDULED_GRACE_SEC:.0f}s)",
        flush=True,
    )

    # Linhas presas em 'firing' de um crash anterior → failed (nunca re-dispara
    # sozinhas; o usuário pode reagendar).
    try:
        n = scheduled_order_repository.fail_firing("worker reiniciado antes do disparo")
        if n:
            print(f"[Scheduled] {n} linha(s) 'firing' órfãs marcadas como failed", flush=True)
    except Exception as e:
        print(f"[Scheduled] fail_firing error: {e}", flush=True)

    try:
        while True:
            try:
                rows = scheduled_order_repository.list(
                    statuses=["pending"], limit=500
                )
                for row in rows:
                    rid = row["id"]
                    task = _scheduled_tasks.get(rid)
                    if task and not task.done():
                        continue
                    _scheduled_tasks[rid] = asyncio.create_task(
                        _fire_scheduled_order(row)
                    )
                # Limpa tasks concluídas
                for rid in [
                    k for k, t in _scheduled_tasks.items() if t.done()
                ]:
                    task = _scheduled_tasks.pop(rid, None)
                    if task and not task.cancelled() and task.exception():
                        print(
                            f"[Scheduled] task {rid} exceção: {task.exception()}",
                            flush=True,
                        )
            except Exception as e:
                print(f"[Scheduled] sync error: {e}", flush=True)
            await asyncio.sleep(SCHEDULED_POLL_SEC)
    except asyncio.CancelledError:
        # Cancela disparos em andamento (o handler marca 'failed')
        for task in list(_scheduled_tasks.values()):
            task.cancel()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação"""
    # Startup
    print("[BrokerGateway] Starting up...")
    
    # Registrar adapter IQ Option
    broker_registry.register("iqoption", IQOptionAdapter())
    
    print("[BrokerGateway] Registered adapters:", broker_registry.list_brokers())
    
    # Load existing connections from database
    try:
        db_connections = connection_repository.list_all()
        print(f"[BrokerGateway] Loaded {len(db_connections)} connections from database")
        for conn in db_connections:
            # Register in memory (status starts as disconnected)
            connection = Connection(
                broker=conn["broker"],
                account_type=conn["account_type"],
            )
            connection.id = conn["id"]
            connection.status = ConnectionStatus.DISCONNECTED
            broker_registry.register_connection(conn["id"], connection)

        # Auto-reconnect: connections que estavam ativas antes do restart
        # (status preservado no banco — ver shutdown abaixo).
        active = [
            c for c in db_connections
            if c.get("status") in ("connected", "ready", "connecting")
        ]
        for conn in active:
            asyncio.create_task(_auto_reconnect_connection(conn["id"]))
        if active:
            print(
                f"[BrokerGateway] Auto-reconnect agendado para "
                f"{len(active)} connection(s)",
                flush=True,
            )
    except Exception as e:
        print(f"[BrokerGateway] Warning: Could not load connections from database: {e}")

    # Worker de ordens agendadas (próxima vela / horário fixo)
    scheduled_worker_task = asyncio.create_task(_scheduled_orders_worker())

    yield
    
    # Shutdown
    print("[BrokerGateway] Shutting down...")

    # Para o worker de agendamento (disparos em andamento marcam 'failed')
    scheduled_worker_task.cancel()
    try:
        await scheduled_worker_task
    except (asyncio.CancelledError, Exception):
        pass
    
    # Desconnect all active connections
    for connection in broker_registry.list_connections():
        try:
            adapter = broker_registry.get_adapter_for_connection(connection.id)
            if adapter:
                await adapter.disconnect()
        except Exception as e:
            print(f"[BrokerGateway] Error disconnecting {connection.id}: {e}")
    
    # NB: NÃO marcar connections como 'disconnected' no banco aqui — o status
    # preservado ("connected"/"ready") permite o auto-reconnect no próximo boot.
    # Disconnect manual continua gravando 'disconnected' no endpoint.
    
    # Clear event history
    event_manager.clear_history()


# Criar aplicação
app = FastAPI(
    title="Broker Gateway",
    description="Multi-broker gateway para integração com plataformas de trading",
    version="1.0.0",
    lifespan=lifespan,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Rotas de health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        db = connection_repository.list_all()
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "healthy",
        "service": "broker-gateway",
        "version": "1.0.0",
        "brokers": broker_registry.list_brokers(),
        "database": db_status,
        "active_connections": len(broker_registry.list_connections()),
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Broker Gateway",
        "version": "1.0.0",
        "docs": "/docs",
    }


# Rotas de brokers
@app.get("/brokers")
async def list_brokers():
    """Lista brokers disponíveis"""
    return {
        "brokers": broker_registry.list_brokers(),
    }


# Rotas de conexões
@app.get("/connections")
async def list_connections(user_id: Optional[str] = None):
    """Lista conexões (escopo multi-tenant via ?user_id=)"""
    # Get from database (includes persisted connections)
    try:
        db_connections = connection_repository.list_all(user_id=user_id or None)
        return {"connections": db_connections}
    except Exception:
        # Fallback to in-memory registry
        connections = broker_registry.list_connections()
        return {
            "connections": [c.model_dump() for c in connections],
        }


@app.post("/connections", response_model=ConnectionResponse)
async def create_connection(config: ConnectRequest):
    """Cria uma nova conexão e conecta ao broker"""
    try:
        # Generate connection name if not provided
        conn_name = config.name or f"{config.account_type.title()} Account"

        # Save to database first
        db_conn = connection_repository.create(
            name=conn_name,
            broker="iqoption",
            email=config.email,
            password=config.password,
            account_type=config.account_type,
            user_id=config.user_id or None,
        )
        connection_id = db_conn["id"]

        # Create in-memory connection
        connection = Connection(
            broker="iqoption",
            account_type=config.account_type,
        )
        connection.id = connection_id
        connection.status = ConnectionStatus.CONNECTING

        # Register in memory
        broker_registry.register_connection(connection_id, connection)

        # Update database status
        connection_repository.update_status(connection_id, "connecting")
        connection_repository.log_event(
            "connection.created",
            connection_id=connection_id,
            event_data={"broker": "iqoption", "account_type": config.account_type},
        )

        # Connect to broker — usa o adapter dedicado desta connection (sessão isolada)
        adapter = broker_registry.get_adapter_for_connection(connection_id)
        if not adapter:
            raise HTTPException(status_code=500, detail="Adapter not initialized")
        result = await adapter.connect({
            "email": config.email,
            "password": config.password,
            "account_type": config.account_type,
        })
        
        # Update status
        connection.status = ConnectionStatus(result["status"])
        connection_repository.update_status(connection_id, result["status"])

        # Persistir ID da conta na corretora (card UI / diagnóstico)
        try:
            account = await adapter.get_account()
            if account and account.id:
                connection_repository.update_account_id(connection_id, str(account.id))
        except Exception as acct_err:
            print(f"[BrokerGateway] Could not persist account_id for {connection_id}: {acct_err}")
        
        # Emit event
        await event_manager.emit("connection.created", {
            "connection_id": connection_id,
            "broker": "iqoption",
            "status": result["status"],
        })
        
        connection_repository.log_event(
            "connection.connected",
            connection_id=connection_id,
            event_data={"status": result["status"]},
        )
        
        account_type_val = connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type
        status_val = connection.status.value if hasattr(connection.status, 'value') else connection.status
        
        return ConnectionResponse(
            id=connection_id,
            broker=connection.broker,
            account_type=account_type_val,
            status=status_val,
            name=conn_name,
        )
        
    except Exception as e:
        # Update database status to error if connection was created
        try:
            if 'connection_id' in locals():
                connection_repository.update_status(connection_id, "error", str(e))
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}")
async def get_connection(connection_id: str):
    """Obtém detalhes de uma conexão"""
    # Try database first
    db_conn = connection_repository.get_by_id(connection_id)
    if db_conn:
        return db_conn
    
    # Fallback to in-memory
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    return connection.model_dump()


@app.put("/connections/{connection_id}")
async def update_connection(connection_id: str, config: UpdateConnectionRequest):
    """Atualiza uma conexão existente"""
    # Check if connection exists
    db_conn = connection_repository.get_by_id(connection_id)
    if not db_conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    try:
        # Disconnect if currently connected
        connection = broker_registry.get_connection(connection_id)
        if connection:
            try:
                adapter = broker_registry.get_adapter_for_connection(connection_id)
                if adapter:
                    await adapter.disconnect()
            except Exception:
                pass
            broker_registry.remove_connection(connection_id)
        
        # Update credentials in database
        # Map field names to database column names
        update_data = {}
        if config.email is not None:
            update_data["email_encrypted"] = config.email
        if config.password is not None:
            update_data["password_encrypted"] = config.password
        if config.account_type is not None:
            update_data["account_type"] = config.account_type
        if config.name is not None:
            update_data["name"] = config.name
        
        if update_data:
            connection_repository._update_fields(connection_id, update_data)
        
        # Reset status to disconnected
        connection_repository.update_status(connection_id, "disconnected")
        
        connection_repository.log_event(
            "connection.updated",
            connection_id=connection_id,
            event_data={"updated_fields": list(update_data.keys())},
        )
        
        # Return updated connection
        updated_conn = connection_repository.get_by_id(connection_id)
        return updated_conn
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str):
    """Remove uma conexão"""
    connection = broker_registry.get_connection(connection_id)

    # Disconnect if active
    if connection:
        try:
            adapter = broker_registry.get_adapter_for_connection(connection_id)
            if adapter:
                await adapter.disconnect()
        except Exception:
            pass

        # Remove from memory
        broker_registry.remove_connection(connection_id)

    # Remove from database (operação principal — deve sempre executar)
    try:
        connection_repository.delete(connection_id)
    except Exception as e:
        print(f"[BrokerGateway] Error deleting connection {connection_id} from DB: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao remover conexão: {e}")

    # Log event (não bloqueia a exclusão se falhar)
    try:
        connection_repository.log_event(
            "connection.deleted",
            connection_id=connection_id,
        )
    except Exception as e:
        print(f"[BrokerGateway] Error logging delete event for {connection_id}: {e}")

    # Emit event (não bloqueia a exclusão se falhar)
    try:
        await event_manager.emit("connection.deleted", {
            "connection_id": connection_id,
        })
    except Exception as e:
        print(f"[BrokerGateway] Error emitting delete event for {connection_id}: {e}")

    return {"message": "Connection deleted"}


@app.post("/connections/{connection_id}/connect")
async def connect_connection(connection_id: str):
    """Conecta uma conexão existente usando credenciais salvas"""
    # Check in-memory registry first
    connection = broker_registry.get_connection(connection_id)
    
    # If not in memory, try to load from database
    if not connection:
        db_conn = connection_repository.get_by_id(connection_id)
        if not db_conn:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        # Create in-memory connection from database
        connection = Connection(
            broker=db_conn["broker"],
            account_type=db_conn["account_type"],
        )
        connection.id = connection_id
        connection.status = ConnectionStatus.DISCONNECTED
        broker_registry.register_connection(connection_id, connection)
    
    # Get adapter
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Adapter not found")
    
    # Get credentials from database
    db_conn = connection_repository.get_with_credentials(connection_id)
    if not db_conn:
        raise HTTPException(status_code=400, detail="Credentials not found")

    # Update status
    connection.status = ConnectionStatus.CONNECTING
    connection_repository.update_status(connection_id, "connecting")
    
    try:
        # Connect using stored credentials
        result = await adapter.connect({
            "email": db_conn.get("email", ""),
            "password": db_conn.get("password", ""),
            "account_type": connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
        })
        
        connection.status = ConnectionStatus(result["status"])
        connection_repository.update_status(connection_id, result["status"])

        # Persistir ID da conta na corretora (card UI / diagnóstico)
        try:
            account = await adapter.get_account()
            if account and account.id:
                connection_repository.update_account_id(connection_id, str(account.id))
        except Exception as acct_err:
            print(f"[BrokerGateway] Could not persist account_id for {connection_id}: {acct_err}")

        connection_repository.log_event(
            "connection.reconnected",
            connection_id=connection_id,
            event_data={"status": result["status"]},
        )
        
        return {"status": result["status"], "message": "Reconnected successfully"}
        
    except Exception as e:
        connection.status = ConnectionStatus.ERROR
        connection_repository.update_status(connection_id, "error", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/connections/{connection_id}/disconnect")
async def disconnect_connection(connection_id: str):
    """Desconecta uma conexão"""
    # Check if connection exists in database
    db_conn = connection_repository.get_by_id(connection_id)
    if not db_conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    # Try to disconnect from in-memory if exists
    connection = broker_registry.get_connection(connection_id)
    if connection:
        adapter = broker_registry.get_adapter_for_connection(connection_id)
        if adapter:
            try:
                await adapter.disconnect()
            except Exception:
                pass
    
    # Update database
    connection_repository.update_status(connection_id, "disconnected")
    connection_repository.log_event(
        "connection.disconnected",
        connection_id=connection_id,
    )
    
    # Emit event
    await event_manager.emit("connection.disconnected", {
        "connection_id": connection_id,
    })
    
    return {"message": "Disconnected"}


@app.get("/connections/{connection_id}/debug")
async def debug_connection(connection_id: str):
    """Debug connection state"""
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        return {"error": "no adapter"}
    
    result = {"connected": adapter._connected}
    
    if hasattr(adapter, '_api') and adapter._api:
        try:
            import iqoptionapi.global_value as gv
            obj_id = adapter._api.api.object_id
            result["object_id"] = obj_id
            result["balance_id"] = gv.balance_id.get(obj_id)
            raw = adapter._api.api.balances_raw
            result["balances_raw_none"] = raw is None
            if raw:
                result["balances"] = raw.get("msg", [])
        except Exception as e:
            result["error"] = str(e)
    
    return result


@app.get("/connections/{connection_id}/status")
async def get_connection_status(connection_id: str):
    """Obtém status de uma conexão"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        return {"status": "disconnected"}
    
    status = await adapter.get_status()
    
    # Update database heartbeat
    connection_repository.update_heartbeat(connection_id)
    
    return status


@app.get("/connections/{connection_id}/account")
async def get_account(connection_id: str):
    """Obtém informações da conta"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    # Auto-connect if adapter is not connected (e.g. after server reload)
    if not adapter._connected:
        db_conn = connection_repository.get_with_credentials(connection_id)
        if db_conn:
            try:
                await adapter.connect({
                    "email": db_conn.get("email", ""),
                    "password": db_conn.get("password", ""),
                    "account_type": connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
                })
            except Exception:
                # Return partial data even if auto-reconnect fails
                return Account(
                    id="",
                    broker="iqoption",
                    type=connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
                    currency="USD",
                    status=ConnectionStatus.READY,
                ).model_dump()
        else:
            return Account(
                id="",
                broker="iqoption",
                type=connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
                currency="USD",
                status=ConnectionStatus.READY,
            ).model_dump()
    
    try:
        account = await adapter.get_account()
        return account.model_dump()
    except Exception as e:
        # Return partial data on error
        return Account(
            id="",
            broker="iqoption",
            type=connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
            currency="USD",
            status=ConnectionStatus.READY,
        ).model_dump()


@app.get("/connections/{connection_id}/balance")
async def get_balance(connection_id: str):
    """Obtém saldo da conta"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    # Auto-connect if adapter is not connected (e.g. after server reload)
    if not adapter._connected:
        db_conn = connection_repository.get_with_credentials(connection_id)
        if db_conn:
            try:
                await adapter.connect({
                    "email": db_conn.get("email", ""),
                    "password": db_conn.get("password", ""),
                    "account_type": connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type,
                })
            except Exception:
                return Balance(
                    available=0.0,
                    currency="USD",
                    total=0.0,
                    updated_at=datetime.utcnow(),
                ).model_dump()
        else:
            return Balance(
                available=0.0,
                currency="USD",
                total=0.0,
                updated_at=datetime.utcnow(),
            ).model_dump()
    
    try:
        balance = await adapter.get_balance()
        return balance.model_dump()
    except Exception as e:
        return Balance(
            available=0.0,
            currency="USD",
            total=0.0,
            updated_at=datetime.utcnow(),
        ).model_dump()


@app.get("/connections/{connection_id}/assets")
async def get_assets(connection_id: str):
    """Lista ativos disponíveis"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        assets = await adapter.get_assets()
        return {"assets": [a.model_dump() for a in assets]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}/assets/{symbol}")
async def get_asset(connection_id: str, symbol: str):
    """Obtém informações de um ativo"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        asset = await adapter.get_asset(symbol)
        return asset.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}/candles")
async def get_candles(
    connection_id: str,
    asset: str,
    timeframe: int = 1,
    count: int = 100,
):
    """Obtém candles históricos"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        candles = await adapter.get_candles(asset, timeframe, count)
        return {"candles": [c.model_dump() for c in candles]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/connections/{connection_id}/orders")
async def place_order(connection_id: str, order: dict):
    """Envia uma ordem"""
    from .core.models import OrderRequest, OrderDirection, AccountType
    
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    db_order = None
    try:
        order_request = OrderRequest(
            asset=order.get("asset"),
            direction=OrderDirection(order.get("direction")),
            amount=order.get("amount"),
            expiration=order.get("expiration", 1),
            account_type=AccountType(connection.account_type if isinstance(connection.account_type, str) else connection.account_type.value),
            connection_id=connection_id,
        )
        
        # Save order to database
        db_order = connection_repository.save_order(
            connection_id=connection_id,
            broker_order_id=None,
            asset=order_request.asset,
            direction=order_request.direction.value if hasattr(order_request.direction, 'value') else order_request.direction,
            amount=order_request.amount,
            expiration=order_request.expiration,
            status="pending",
        )
        
        # Place order via broker
        result = await adapter.place_order(order_request)

        # Update order with broker ID/status (accepted OR rejected)
        final_status = result.status.value if hasattr(result.status, 'value') else str(result.status)
        connection_repository.update_order(
            order_id=db_order["id"],
            status=final_status,
            broker_order_id=result.id,
        )

        connection_repository.log_event(
            "order.placed" if result.id else "order.rejected",
            connection_id=connection_id,
            event_data={
                "order_id": db_order["id"],
                "asset": order_request.asset,
                "status": final_status,
                "error": result.error,
            },
        )

        return result.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        # Falha após salvar (ex: ativo fechado via BrokerError): marca a
        # ordem como rejected para não ficar pending para sempre.
        if db_order:
            try:
                connection_repository.update_order(
                    order_id=db_order["id"],
                    status="rejected",
                )
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}/orders/{order_id}")
async def get_order(connection_id: str, order_id: str):
    """Obtém status de uma ordem"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        order = await adapter.get_order(order_id)
        return order.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}/orders/{order_id}/result")
async def get_order_result(connection_id: str, order_id: str):
    """Obtém resultado de uma ordem"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        result = await adapter.get_order_result(order_id)
        
        # Update order in database if result is available
        if result.result:
            connection_repository.update_order(
                order_id=order_id,
                status="closed",
                result=result.result.value if hasattr(result.result, 'value') else result.result,
                profit=result.profit,
                payout=result.payout,
            )
        
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ScheduledOrderCreate(BaseModel):
    connection_id: str
    asset: str
    direction: str  # CALL | PUT
    amount: float
    expiration: int = 1
    mode: str = "next_candle"  # next_candle | fixed_time
    timeframe: Optional[str] = None
    scheduled_for: str  # ISO UTC


@app.post("/scheduled-orders")
async def create_scheduled_order(body: ScheduledOrderCreate):
    """Cria uma ordem agendada (worker dispara em scheduled_for)."""
    connection = broker_registry.get_connection(body.connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if body.direction.upper() not in ("CALL", "PUT"):
        raise HTTPException(status_code=400, detail="direction deve ser CALL ou PUT")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount deve ser > 0")
    if body.mode not in ("next_candle", "fixed_time"):
        raise HTTPException(status_code=400, detail="mode inválido")

    try:
        dt = datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="scheduled_for inválido (ISO)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    ahead = (dt - datetime.now(timezone.utc)).total_seconds()
    if ahead < 1.5:
        raise HTTPException(
            status_code=400,
            detail="scheduled_for muito próximo (mínimo 1.5s no futuro)",
        )

    row = scheduled_order_repository.create(
        connection_id=body.connection_id,
        asset=body.asset,
        direction=body.direction.upper(),
        amount=body.amount,
        expiration=body.expiration,
        scheduled_for=dt.isoformat(),
        mode=body.mode,
        timeframe=body.timeframe,
    )
    connection_repository.log_event(
        "order.scheduled_created",
        connection_id=body.connection_id,
        event_data={
            "scheduled_order_id": row["id"],
            "asset": body.asset,
            "direction": body.direction.upper(),
            "mode": body.mode,
            "timeframe": body.timeframe,
            "scheduled_for": dt.isoformat(),
        },
    )
    return row


@app.get("/scheduled-orders")
async def list_scheduled_orders(
    connection_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """Lista ordens agendadas (opcionalmente por conexão/status)."""
    rows = scheduled_order_repository.list(
        connection_id=connection_id,
        statuses=[status] if status else None,
        limit=min(limit, 200),
    )
    return {"scheduled_orders": rows}


@app.delete("/scheduled-orders/{order_id}")
async def cancel_scheduled_order(order_id: str):
    """Cancela uma ordem agendada (apenas se ainda pending)."""
    if scheduled_order_repository.cancel(order_id):
        connection_repository.log_event(
            "order.scheduled_cancelled",
            event_data={"scheduled_order_id": order_id},
        )
        return {"cancelled": True}
    row = scheduled_order_repository.get_by_id(order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    raise HTTPException(
        status_code=409,
        detail=f"Não cancelável: status atual '{row.get('status')}'",
    )


@app.get("/events")
async def get_events(limit: int = 100):
    """Obtém histórico de eventos"""
    events = event_manager.get_history(limit)
    return {"events": events}


# Ponto de entrada
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "src.server:app",
        host=host,
        port=port,
        reload=True,
    )