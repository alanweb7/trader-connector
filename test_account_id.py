import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def debug_account_info():
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
        print(f"Account ID: '{account.id}'")
        print(f"Account type: {account.type}")
        print(f"Account currency: {account.currency}")
        print(f"Account status: {account.status}")
        
        # DEBUG: Tentar obter profile_msg diretamente
        print("\n=== DEBUG: Obter profile_msg diretamente ===")
        if adapter._api and hasattr(adapter._api, 'api'):
            try:
                profile_msg = adapter._api.api.profile.msg
                print(f"profile_msg type: {type(profile_msg)}")
                print(f"profile_msg: {profile_msg}")
                if isinstance(profile_msg, dict):
                    print(f"profile_msg keys: {list(profile_msg.keys())}")
                    if 'id' in profile_msg:
                        print(f"profile_msg['id']: '{profile_msg['id']}'")
                    else:
                        print("Nenhuma chave 'id' no profile_msg")
            except Exception as e:
                print(f"Erro ao obter profile_msg: {e}")
        else:
            print("adapter._api ou adapter._api.api não está disponível")
        
        # DEBUG: Tentar obter outros atributos da API
        print("\n=== DEBUG: Outros atributos da API ===")
        if adapter._api and hasattr(adapter._api, 'api'):
            api = adapter._api.api
            print(f"api type: {type(api)}")
            print(f"api has profile: {hasattr(api, 'profile')}")
            if hasattr(api, 'profile'):
                print(f"profile type: {type(api.profile)}")
                print(f"profile attributes: {[attr for attr in dir(api.profile) if not attr.startswith('_')]}")
        
        await adapter.disconnect()
        print("\nDisconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_account_info())
