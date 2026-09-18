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

async def test_sell_order_simple():
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
        
        # Obter timestamp do servidor para expiração
        server_ts = await asyncio.to_thread(adapter._api.get_server_timestamp)
        expiration = server_ts + 60  # 1 minuto a partir de agora
        print(f"Server timestamp: {server_ts}, Expiration: {expiration}")
        
        # Tentar obter dados do ativo diretamente (para AUDUSD-OTC)
        print("Tentando obter dados do ativo AUDUSD-OTC...")
        asset_data = await adapter._get_asset_data("AUDUSD-OTC")
        
        if asset_data:
            print(f"Dados do ativo AUDUSD-OTC: {asset_data}")
            print(f"Status (aberto/fechado): {asset_data.get('open', 'NOT_SET')}")
        else:
            print("Não foi possível obter dados do ativo AUDUSD-OTC")
            # Tentar um ativo genérico conhecido
            asset_data = await adapter._get_asset_data("EURUSD")
            if asset_data:
                print(f"Dados do ativo EURUSD: {asset_data}")
                print(f"Status (aberto/fechado): {asset_data.get('open', 'NOT_SET')}")
            else:
                print("Não foi possível obter dados do ativo EURUSD")
        
        # Tentar obter informações de algum ativo para depuração
        print("\nTentando obter ativos para depuração...")
        try:
            assets = await adapter.get_assets()
            print(f"Total de ativos: {len(assets)}")
            if assets:
                print("Primeiros 5 ativos:")
                for asset in assets[:5]:
                    print(f"  - {asset.symbol}: type={asset.type}, status={asset.status}, payout={asset.payout}%")
        except Exception as e:
            print(f"Erro ao obter ativos: {e}")
        
        # Tentar colocar uma ordem de VENDA de $10
        print(f"\nTentando enviar ordem de VENDA de 10 unidades")
        order = OrderRequest(
            asset="AUDUSD-OTC",
            direction=OrderDirection.PUT,  # VENDA = PUT
            amount=10.0,
            expiration=expiration,
            connection_id="test",
            request_id="test"
        )
        
        print(f"Enviando ordem: asset={order.asset}, direction={order.direction}, amount={order.amount}, expiration={order.expiration}")
        response = await adapter.place_order(order)
        print(f"Ordem enviada - Status: {response.status}, ID: {response.id}")
        if response.error:
            print(f"Erro: {response.error}")
        else:
            print("SUCESSO: Ordem enviada!")
        
        await adapter.disconnect()
        print("\nDisconnected")
        
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sell_order_simple())
