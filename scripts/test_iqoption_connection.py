"""
Script de teste para conexão com IQ Option
Execute: python scripts/test_iqoption_connection.py
"""
import asyncio
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()


async def test_connection():
    """Testa conexão básica com IQ Option"""
    from src.adapters.iqoption import IQOptionAdapter
    from src.core.errors import BrokerError

    print("=" * 60)
    print("TESTE DE CONEXÃO COM IQ OPTION")
    print("=" * 60)
    print()

    # Verificar credenciais
    email = os.getenv("IQOPTION_EMAIL")
    password = os.getenv("IQOPTION_PASSWORD")
    account_type = os.getenv("IQOPTION_ACCOUNT_TYPE", "practice")

    if not email or not password:
        print("❌ ERRO: Credenciais não configuradas!")
        print()
        print("Configure o arquivo .env:")
        print("  IQOPTION_EMAIL=seu_email@example.com")
        print("  IQOPTION_PASSWORD=sua_senha")
        print("  IQOPTION_ACCOUNT_TYPE=practice")
        return

    print(f"📧 Email: {email}")
    print(f"🔑 Conta: {account_type}")
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
        print(f"   ✅ {result['message']}")
        print()

        # 2. Verificar status
        print("2. Verificando status...")
        status = await adapter.get_status()
        print(f"   📊 Status: {status['status']}")
        print()

        # 3. Obter conta
        print("3. Obtendo informações da conta...")
        account = await adapter.get_account()
        print(f"   👤 ID: {account.id}")
        print(f"   💰 Moeda: {account.currency}")
        print()

        # 4. Obter saldo
        print("4. Obtendo saldo...")
        balance = await adapter.get_balance()
        print(f"   💵 Saldo: {balance.available} {balance.currency}")
        print()

        # 5. Listar ativos
        print("5. Listando ativos disponíveis...")
        assets = await adapter.get_assets()
        print(f"   📈 Total de ativos: {len(assets)}")
        if assets:
            print("   Primeiros 5 ativos:")
            for asset in assets[:5]:
                print(f"     - {asset.symbol}: payout {asset.payout}%")
        print()

        # 6. Obter candles
        if assets:
            print("6. Obtendo candles do primeiro ativo...")
            first_asset = assets[0].symbol
            candles = await adapter.get_candles(first_asset, 1, 10)
            print(f"   📊 Candles de {first_asset}: {len(candles)}")
            if candles:
                last_candle = candles[-1]
                print(f"   Último candle: O={last_candle.open} H={last_candle.high} L={last_candle.low} C={last_candle.close}")
        print()

        # 7. Desconectar
        print("7. Desconectando...")
        await adapter.disconnect()
        print("   ✅ Desconectado")
        print()

        print("=" * 60)
        print("✅ TODOS OS TESTES PASSARAM!")
        print("=" * 60)

    except BrokerError as e:
        print(f"\n❌ ERRO DO BROKER: {e.message}")
        print(f"   Código: {e.code}")
        if e.original_error:
            print(f"   Erro original: {e.original_error}")
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_connection())