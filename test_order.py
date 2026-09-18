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

async def test_order():
    from src.adapters.iqoption import IQOptionAdapter
    from src.core.models import OrderRequest, OrderDirection
    
    adapter = IQOptionAdapter()
    
    try:
        # Conectar
        result = await adapter.connect({
            'email': os.environ['IQOPTION_EMAIL'],
            'password': os.environ['IQOPTION_PASSWORD'],
            'account_type': 'practice',
        })
        print('Connect result:', result)
        
        # Obter ativos para ver o que está disponível
        print("Obtendo ativos...")
        assets = await adapter.get_assets()
        print(f"Total de ativos: {len(assets)}")
        
        if assets:
            # Pegar o primeiro ativo disponível
            test_asset = assets[0].symbol
            print(f"Testando com ativo: {test_asset}")
            
            # Tentar colocar uma ordem (valor baixo para safety)
            print(f"Tentando enviar ordem de CALL de 1 unidade do {test_asset}")
            order = OrderRequest(
                asset=test_asset,
                direction=OrderDirection.CALL,
                amount=1.0,
                expiration=1,
                connection_id="test",
                request_id="test"
            )
            
            response = await adapter.place_order(order)
            print(f"Ordem enviada - Status: {response.status}, ID: {response.id}")
        else:
            print("Nenhum ativo disponível para teste de ordem")
            
        await adapter.disconnect()
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_order())
