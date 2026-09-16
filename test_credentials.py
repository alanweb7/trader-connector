import asyncio
import os
import sys

# Adicionar diretorio raiz ao path para importacoes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

# Definir credenciais de teste
os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def test():
    from src.adapters.iqoption import IQOptionAdapter
    adapter = IQOptionAdapter()
    
    try:
        result = await adapter.connect({
            'email': '99tisistemas@gmail.com',
            'password': '@123Mudar',
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