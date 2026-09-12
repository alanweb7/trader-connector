"""
Servidor principal do Broker Gateway
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core.models import Connection, ConnectionStatus, BrokerConfig
from .core.registry.broker_registry import broker_registry
from .core.events.event_manager import event_manager
from .adapters.iqoption import IQOptionAdapter

# Carregar variáveis de ambiente
load_dotenv()


# Modelos para request/response
class ConnectRequest(BaseModel):
    email: str
    password: str
    account_type: str = "practice"


class ConnectionResponse(BaseModel):
    id: str
    broker: str
    account_type: str
    status: str


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
    
    yield
    
    # Shutdown
    print("[BrokerGateway] Shutting down...")
    
    # Desconectar todas as conexões
    for connection in broker_registry.list_connections():
        try:
            adapter = broker_registry.get_adapter_for_connection(connection.id)
            if adapter:
                await adapter.disconnect()
        except Exception as e:
            print(f"[BrokerGateway] Error disconnecting {connection.id}: {e}")
    
    # Limpar histórico de eventos
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
    return {
        "status": "healthy",
        "service": "broker-gateway",
        "version": "1.0.0",
        "brokers": broker_registry.list_brokers(),
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
async def list_connections():
    """Lista conexões ativas"""
    connections = broker_registry.list_connections()
    return {
        "connections": [c.model_dump() for c in connections],
    }


@app.post("/connections", response_model=ConnectionResponse)
async def create_connection(config: ConnectRequest):
    """Cria uma nova conexão"""
    try:
        # Criar conexão
        connection = Connection(
            broker="iqoption",
            account_type=config.account_type,
        )
        
        # Registrar conexão
        broker_registry.register_connection(str(connection.id), connection)
        
        # Conectar
        adapter = broker_registry.get("iqoption")
        result = await adapter.connect({
            "email": config.email,
            "password": config.password,
            "account_type": config.account_type,
        })
        
        # Atualizar status
        connection.status = ConnectionStatus(result["status"])
        
        # Emitir evento
        await event_manager.emit("connection.created", {
            "connection_id": str(connection.id),
            "broker": "iqoption",
            "status": result["status"],
        })
        
        account_type_val = connection.account_type.value if hasattr(connection.account_type, 'value') else connection.account_type
        status_val = connection.status.value if hasattr(connection.status, 'value') else connection.status
        
        return ConnectionResponse(
            id=str(connection.id),
            broker=connection.broker,
            account_type=account_type_val,
            status=status_val,
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}")
async def get_connection(connection_id: str):
    """Obtém detalhes de uma conexão"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    return connection.model_dump()


@app.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str):
    """Remove uma conexão"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    # Desconectar
    try:
        adapter = broker_registry.get_adapter_for_connection(connection_id)
        if adapter:
            await adapter.disconnect()
    except Exception:
        pass
    
    # Remover
    broker_registry.remove_connection(connection_id)
    
    # Emitir evento
    await event_manager.emit("connection.deleted", {
        "connection_id": connection_id,
    })
    
    return {"message": "Connection deleted"}


@app.post("/connections/{connection_id}/connect")
async def connect_connection(connection_id: str):
    """Conecta uma conexão existente"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Adapter not found")
    
    # TODO: Precisaria armazenar credenciais de forma segura
    # Por enquanto, retornar erro
    raise HTTPException(
        status_code=501,
        detail="Reconnection not implemented yet. Create a new connection."
    )


@app.post("/connections/{connection_id}/disconnect")
async def disconnect_connection(connection_id: str):
    """Desconecta uma conexão"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Adapter not found")
    
    await adapter.disconnect()
    connection.status = ConnectionStatus.DISCONNECTED
    
    # Emitir evento
    await event_manager.emit("connection.disconnected", {
        "connection_id": connection_id,
    })
    
    return {"message": "Disconnected"}


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
    
    try:
        account = await adapter.get_account()
        return account.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/connections/{connection_id}/balance")
async def get_balance(connection_id: str):
    """Obtém saldo da conta"""
    connection = broker_registry.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    adapter = broker_registry.get_adapter_for_connection(connection_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="Not connected")
    
    try:
        balance = await adapter.get_balance()
        return balance.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
        
        result = await adapter.place_order(order_request)
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