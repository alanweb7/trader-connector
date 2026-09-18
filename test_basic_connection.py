import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

# Credenciais devem vir do ambiente. Sem fallback hardcoded.
if not os.environ.get('IQOPTION_EMAIL') or not os.environ.get('IQOPTION_PASSWORD'):
    raise SystemExit(
        'Defina IQOPTION_EMAIL e IQOPTION_PASSWORD no ambiente antes de executar. '
        'Ex: IQOPTION_EMAIL=user@x.com IQOPTION_PASSWORD=secret python ' + __file__
    )

async def test_basic():
    from src.adapters.iqoption import IQOptionAdapter
    
    adapter = IQOptionAdapter()
    
    try:
        # Conectar
        result = await adapter.connect({
            'email': os.environ['IQOPTION_EMAIL'],
            'password': os.environ['IQOPTION_PASSWORD'],
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
