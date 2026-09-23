"""
Servidor principal do Broker Gateway
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core.models import Connection, ConnectionStatus, BrokerConfig, Account, Balance
from .core.registry.broker_registry import broker_registry
from .core.events.event_manager import event_manager
from .adapters.iqoption import IQOptionAdapter
from .infrastructure.database.connection_repository import connection_repository

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
    except Exception as e:
        print(f"[BrokerGateway] Warning: Could not load connections from database: {e}")
    
    yield
    
    # Shutdown
    print("[BrokerGateway] Shutting down...")
    
    # Desconnect all active connections
    for connection in broker_registry.list_connections():
        try:
            adapter = broker_registry.get_adapter_for_connection(connection.id)
            if adapter:
                await adapter.disconnect()
        except Exception as e:
            print(f"[BrokerGateway] Error disconnecting {connection.id}: {e}")
    
    # Update all connection statuses to disconnected in database
    try:
        for connection in broker_registry.list_connections():
            connection_repository.update_status(connection.id, "disconnected")
    except Exception as e:
        print(f"[BrokerGateway] Error updating statuses: {e}")
    
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
        
        # Update order with broker ID and status
        if result.id:
            connection_repository.update_order(
                order_id=db_order["id"],
                status=result.status.value if hasattr(result.status, 'value') else result.status,
            )
        
        connection_repository.log_event(
            "order.placed",
            connection_id=connection_id,
            event_data={"order_id": db_order["id"], "asset": order_request.asset},
        )
        
        return result.model_dump()
    except Exception as e:
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