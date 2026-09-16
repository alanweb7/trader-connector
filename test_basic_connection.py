import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def test_basic():
    from src.adapters.iqoption import IQOptionAdapter
    
    adapter = IQOptionAdapter()
    
    try:
        # Conectar
        result = await adapter.connect({
            'email': '99tisistemas@gmail.com',
            'password': '@seguro#LIVE332',
            'account_type': 'practice',
        })
        print('Connect result:', result)
        
        # Verificar se realmente estamos conectados
        print("Verificando status...")
        status = await adapter.get_status()
        print(f"Status: {status}")
        
        # Tentar obter o timestamp do servidor
        if adapter._api:
            try:
                server_ts = await asyncio.to_thread(adapter._api.get_server_timestamp)
                print(f"Server timestamp: {server_ts}")
            except Exception as e:
                print(f"Erro ao obter timestamp: {e}")
        
        await adapter.disconnect()
        print("Disconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_basic())
