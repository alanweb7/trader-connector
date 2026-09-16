import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def test_sell_order_fixed():
    from src.adapters.iqoption import IQOptionAdapter
    from src.core.models import OrderRequest, OrderDirection
    
    adapter = IQOptionAdapter()
    
    try:
        # Conectar
        result = await adapter.connect({
            'email': '99tisistemas@gmail.com',
            'password': '@seguro#LIVE332',
            'account_type': 'practice',
        })
        print('Connect result:', result)
        
        # Obter timestamp do servidor para expiração
        server_ts = await asyncio.to_thread(adapter._api.get_server_timestamp)
        print(f"Server timestamp: {server_ts}")
        
        # Tentar colocar uma ordem de VENDA de $10
        # Usar timestamp inteiro para expiração
        expiration = int(server_ts + 60)  # 1 minuto a partir de agora, convertido para int
        print(f"Usando expiração: {expiration}")
        
        # Gerar UUID válido para request_id
        request_id = str(uuid.uuid4())
        
        print(f"Tentando enviar ordem de VENDA de 10 unidades")
        print(f"Ativo: AUDUSD-OTC (ou EURUSD)")
        print(f"Direção: PUT (VENDA)")
        print(f"Valor: $10.00")
        print(f"Expiração: {expiration}")
        
        order = OrderRequest(
            asset="EURUSD",
            direction=OrderDirection.PUT,  # VENDA = PUT
            amount=10.0,
            expiration=expiration,
            connection_id=str(uuid.uuid4()),
            request_id=request_id
        )
        
        print(f"\nEnviando ordem...")
        response = await adapter.place_order(order)
        print(f"Ordem enviada - Status: {response.status}, ID: {response.id}")
        if response.error:
            print(f"Erro: {response.error}")
        else:
            print("SUCESSO: Ordem enviada!")
        
        await adapter.disconnect()
        print("\nDisconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sell_order_fixed())
