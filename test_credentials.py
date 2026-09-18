import asyncio
import os
import sys

# Adicionar diretorio raiz ao path para importacoes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

# Definir credenciais de teste
# Credenciais devem vir do ambiente. Sem fallback hardcoded.
if not os.environ.get('IQOPTION_EMAIL') or not os.environ.get('IQOPTION_PASSWORD'):
    raise SystemExit(
        'Defina IQOPTION_EMAIL e IQOPTION_PASSWORD no ambiente antes de executar. '
        'Ex: IQOPTION_EMAIL=user@x.com IQOPTION_PASSWORD=secret python ' + __file__
    )

async def test():
    from src.adapters.iqoption import IQOptionAdapter
    adapter = IQOptionAdapter()
    
    try:
        result = await adapter.connect({
            'email': os.environ['IQOPTION_EMAIL'],
            'password': os.environ['IQOPTION_PASSWORD'],
            'account_type': 'practice',
        })
        print('Connect result:', result)
        
        status = await adapter.get_status()
        print('Status:', status)
        
        account = await adapter.get_account()
        print('Account ID:', account.id)
        print('Account currency:', account.currency)
        
        balance = await adapter.get_balance()
        print('Balance available:', balance.available)
        print('Balance currency:', balance.currency)
        
        await adapter.disconnect()
        print('Disconnected')
    except Exception as e:
        print('Error:', e)
        import traceback
        traceback.print_exc()

asyncio.run(test())