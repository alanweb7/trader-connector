import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def get_balance():
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
