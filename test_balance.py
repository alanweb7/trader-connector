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

async def get_balance():
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
        
        # Obter informações da conta
        print("Obtendo informações da conta...")
        account = await adapter.get_account()
        print(f"Account ID: {account.id}")
        print(f"Account type: {account.type}")
        print(f"Account currency: {account.currency}")
        print(f"Account status: {account.status}")
        
        # Obter saldo
        print("\nObtendo saldo...")
        balance = await adapter.get_balance()
        print(f"Balance available: {balance.available}")
        print(f"Balance total: {balance.total}")
        print(f"Balance currency: {balance.currency}")
        print(f"Balance updated at: {balance.updated_at}")
        
        # Obter status
        print("\nObtendo status...")
        status = await adapter.get_status()
        print(f"Status: {status}")
        
        await adapter.disconnect()
        print("\nDisconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(get_balance())
