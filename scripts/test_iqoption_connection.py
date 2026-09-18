"""
Script de teste para conexao com IQ Option
Execute: python scripts/test_iqoption_connection.py
"""
import asyncio
import os
import sys

# Adicionar diretorio raiz ao path para importacoes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Carregar variaveis de ambiente
load_dotenv()


async def test_connection():
    """Testa conexao basica com IQ Option"""
    from src.adapters.iqoption import IQOptionAdapter
    from src.core.errors import BrokerError

    print("=" * 60)
    print("TESTE DE CONEXAO COM IQ OPTION")
    print("=" * 60)
    print()

    # Verificar credenciais
    email = os.getenv("IQOPTION_EMAIL")
    password = os.getenv("IQOPTION_PASSWORD")
    account_type = os.getenv("IQOPTION_ACCOUNT_TYPE", "practice")

    if not email or not password:
        print("ERRO: Credenciais nao configuradas!")
        print()
        print("Defina IQOPTION_EMAIL e IQOPTION_PASSWORD no ambiente antes de executar:")
        print("  IQOPTION_EMAIL=user@example.com IQOPTION_PASSWORD=secret python scripts/test_iqoption_connection.py")
        return

    print("Email:", email)
    print("Conta:", account_type)
    print()

    # Criar adapter
    adapter = IQOptionAdapter()

    try:
        # 1. Conectar
        print("1. Conectando...")
        result = await adapter.connect({
            "email": email,
            "password": password,
            "account_type": account_type,
        })
        print("Conectado:", result['message'])
        print()

        # 2. Verificar status
        print("2. Verificando status...")
        status = await adapter.get_status()
        print("Status:", status['status'])
        print()

        # 3. Obter conta
        print("3. Obtendo informacoes da conta...")
        account = await adapter.get_account()
        print("ID:", account.id)
        print("Moeda:", account.currency)
        print()

        # 4. Obter saldo
        print("4. Obtendo saldo...")
        balance = await adapter.get_balance()
        print("Saldo:", balance.available, balance.currency)
        print()

        # 5. Listar ativos
        print("5. Listando ativos disponiveis...")
        assets = await adapter.get_assets()
        print("Total de ativos:", len(assets))
        if assets:
            print("Primeiros 5 ativos:")
            for asset in assets[:5]:
                print("  -", asset.symbol, ": payout", asset.payout, "%")
        print()

        # 6. Obter candles
        if assets:
            print("6. Obtendo candles do primeiro ativo...")
            first_asset = assets[0].symbol
            candles = await adapter.get_candles(first_asset, 1, 10)
            print("Candles de", first_asset, ":", len(candles))
            if candles:
                last_candle = candles[-1]
                print("Ultimo candle: O=", last_candle.open, "H=", last_candle.high, "L=", last_candle.low, "C=", last_candle.close)
        print()

        # 7. Desconectar
        print("7. Desconectando...")
        await adapter.disconnect()
        print("Desconectado")
        print()

        print("=" * 60)
        print("TESTES CONCLUIDOS")
        print("=" * 60)

    except BrokerError as e:
        print("\nERRO DO BROKER:", e.message)
        print("Codigo:", e.code)
        if e.original_error:
            print("Erro original:", e.original_error)
    except Exception as e:
        print("\nERRO INESPERADO:", str(e))
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_connection())