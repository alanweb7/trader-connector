import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(r'E:\apps\01 - TRADER\CONNECTOR\.env')

os.environ['IQOPTION_EMAIL'] = '99tisistemas@gmail.com'
os.environ['IQOPTION_PASSWORD'] = '@seguro#LIVE332'

async def place_sell_order():
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
        
        # Obter ativos para verificar se AUDUSD-OTC está disponível
        print("Obtendo ativos...")
        assets = await adapter.get_assets()
        print(f"Total de ativos: {len(assets)}")
        
        # Procurar por AUDUSD-OTC
        test_asset = None
        for asset in assets:
            if "AUDUSD" in asset.symbol:
                test_asset = asset.symbol
                print(f"Encontrado: {asset.symbol} - Status: {asset.status} - Payout: {asset.payout}%")
                break
        
        if not test_asset:
            # Tentar um ativo binário genérico conhecido
            test_asset = "EURUSD"
            print(f"AUDUSD-OTC não encontrado, usando {test_asset}")
        
        # Obter timestamp do servidor para expiração
        server_ts = await asyncio.to_thread(adapter._api.get_server_timestamp)
        expiration = server_ts + 60  # 1 minuto a partir de agora
        print(f"Usando ativo: {test_asset}, Expiration: {expiration}")
        
        # Tentar obter dados do ativo para verificar se está aberto
        asset_data = await adapter._get_asset_data(test_asset)
        if asset_data:
            print(f"Dados do ativo: {asset_data}")
            if not asset_data.get("open", False):
                print(f"ALERTA: Ativo {test_asset} está fechado")
        else:
            print(f"Não foi possível obter dados do ativo para {test_asset}")
        
        # Tentar colocar uma ordem de VENDA de $10
        print(f"Tentando enviar ordem de VENDA de 10 unidades do {test_asset}")
        order = OrderRequest(
            asset=test_asset,
            direction=OrderDirection.PUT,  # VENDA = PUT
            amount=10.0,
            expiration=expiration,
            connection_id="test",
            request_id="test"
        )
        
        response = await adapter.place_order(order)
        print(f"Ordem enviada - Status: {response.status}, ID: {response.id}")
        if response.error:
            print(f"Erro: {response.error}")
        
        await adapter.disconnect()
        print("\nDisconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(place_sell_order())
