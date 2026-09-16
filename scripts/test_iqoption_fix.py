"""
Teste de conexão IQ Option - conta de prática
Executar: python scripts/test_iqoption_fix.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.adapters.iqoption import IQOptionAdapter
from src.core.errors import BrokerError

EMAIL = os.getenv("IQOPTION_EMAIL", "99tisistemas@gmail.com")
PASSWORD = os.getenv("IQOPTION_PASSWORD", "@seguro#LIVE332")
ACCOUNT_TYPE = os.getenv("IQOPTION_ACCOUNT_TYPE", "practice")


async def test():
    print("=" * 60)
    print("TESTE DE CONEXAO COM IQ OPTION")
    print("=" * 60)
    print(f"\nEmail: {EMAIL}")
    print(f"Conta: {ACCOUNT_TYPE}")
    print()

    adapter = IQOptionAdapter()

    try:
        # 1. Conectar
        print("1. Conectando...")
        result = await adapter.connect({
            "email": EMAIL,
            "password": PASSWORD,
            "account_type": ACCOUNT_TYPE,
        })
        print(f"   Status: {result['status']}")
        print(f"   Mensagem: {result['message']}")
        print()

        # 2. Verificar status
        print("2. Verificando status...")
        status = await adapter.get_status()
        print(f"   Status: {status['status']}")
        print()

        # 3. Obter conta
        print("3. Obtendo informacoes da conta...")
        account = await adapter.get_account()
        print(f"   ID: {account.id}")
        print(f"   Tipo: {account.type}")
        print(f"   Moeda: {account.currency}")
        print(f"   Status: {account.status}")
        print()

        # 4. Obter saldo (melhorado)
        print("4. Obtendo saldo...")
        balance = await adapter.get_balance()
        print(f"   Saldo disponivel: {balance.available} {balance.currency}")
        print(f"   Saldo total: {balance.total} {balance.currency}")
        print()

        # 5. Listar ativos
        print("5. Listando ativos disponiveis...")
        assets = await adapter.get_assets()
        print(f"   Total de ativos: {len(assets)}")
        if assets:
            print("   Primeiros 10 ativos:")
            for i, asset in enumerate(assets[:10]):
                print(f"     {i+1}. {asset.symbol:20s} | payout: {asset.payout:5.1f}% | status: {asset.status}")
            print()

            # 6. Testar candles
            print("6. Testando candles...")
            first_asset = assets[0].symbol
            try:
                candles = await adapter.get_candles(first_asset, 1, 5)
                print(f"   Candles de {first_asset}: {len(candles)} obtidos")
                if candles:
                    last = candles[-1]
                    print(f"   Ultimo candle: O={last.open:.5f} H={last.high:.5f} L={last.low:.5f} C={last.close:.5f}")
            except Exception as e:
                print(f"   Erro ao obter candles: {e}")
            print()

            # 7. TESTE REAL DE ORDEM (apenas se tiver saldo)
            if balance.available > 0:
                print("7. TESTE DE ORDEM (PRATICA)")
                print(f"   Saldo disponivel: {balance.available}")
                print()

                # Tentar um CALL pequeno
                try:
                    test_order = {
                        "asset": first_asset,
                        "direction": "CALL",
                        "amount": min(balance.available, 1.0),
                        "expiration": 1,
                        "connection_id": "test",
                    }

                    print(f"   Enviaendo ORDER: {test_order['amount']} {test_order['direction']} em {test_order['asset']} (exp: {test_order['expiration']}min)")
                    order_result = await adapter.place_order(test_order)
                    print(f"   ID da ordem: {order_result.id}")
                    print(f"   Status: {order_result.status}")

                    if order_result.id:
                        print()
                        print("   Aguardando resultado...")
                        import asyncio
                        for i in range(30):  # 30 segundos max
                            await asyncio.sleep(1)
                            try:
                                order_status = await adapter.get_order(order_result.id)
                                print(f"   Status da ordem: {order_status.status}")
                                if order_status.status in ["closed", "win", "loss", "draw"]:
                                    result = await adapter.get_order_result(order_result.id)
                                    print(f"   Resultado: {result.result} | Profit: {result.profit}")
                                    break
                            except Exception as e:
                                pass
                except Exception as e:
                    print(f"   Erro ao enviar ordem: {e}")
            else:
                print("7. SKIP: Saldo indisponivel para teste de ordem")
            print()

        # 8. Desconectar
        print("8. Desconectando...")
        await adapter.disconnect()
        print("   Desconectado com sucesso")
        print()

        print("=" * 60)
        print("TESTE CONCLUIDO COM SUCESSO")
        print("=" * 60)

    except BrokerError as e:
        print(f"\nERRO DO BROKER: {e.message}")
        print(f"Codigo: {e.code}")
        if e.original_error:
            print(f"Erro original: {e.original_error}")
    except Exception as e:
        print(f"\nERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if adapter._connected:
            try:
                await adapter.disconnect()
            except:
                pass


if __name__ == "__main__":
    asyncio.run(test())
