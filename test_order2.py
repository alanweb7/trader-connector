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
        
        # Aguardar um pouco para a conexão estabilizar
        await asyncio.sleep(2)
        
        # Verificar se estamos realmente conectados
        status = await adapter.get_status()
        print(f"Status: {status}")
        
        # Tentar obter um ativo específico conhecido (EURUSD)
        print("Obtendo ativos...")
        try:
            assets = await adapter.get_assets()
            print(f"Total de ativos: {len(assets)}")
            
            # Procurar um ativo binário válido
            test_asset = None
            for asset in assets:
                if asset.type == "binary" and asset.status.value == "open":
                    test_asset = asset.symbol
                    break
            
            if not test_asset and assets:
                test_asset = assets[0].symbol
                
            if test_asset:
                print(f"Testando com ativo: {test_asset}")
                
                # Obter timestamp do servidor para expiração
                server_ts = await asyncio.to_thread(adapter._api.get_server_timestamp)
                expiration = server_ts + 60  # 1 minuto a partir de agora
                print(f"Usando expiração: {expiration}")
                
                # Tentar colocar uma ordem (valor baixo para safety)
                print(f"Tentando enviar ordem de CALL de 1 unidade do {test_asset}")
                order = OrderRequest(
                    asset=test_asset,
                    direction=OrderDirection.CALL,
                    amount=1.0,
                    expiration=expiration,
                    connection_id="test",
                    request_id="test"
                )
                
                response = await adapter.place_order(order)
                print(f"Ordem enviada - Status: {response.status}, ID: {response.id}")
            else:
                print("Nenhum ativo disponível para teste de ordem")
                
        except Exception as e:
            print(f"Erro ao tentar obter/enviar ordem: {e}")
            import traceback
            traceback.print_exc()
            
        await adapter.disconnect()
        print("Disconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_order())
