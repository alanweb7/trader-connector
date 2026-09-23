"""
Teste de multi-conexão simultânea com IQ Option.

Valida que 2 adapters IQOptionAdapter podem estar conectados ao mesmo tempo:
  - Conta A connect → saldo A
  - Conta B connect → saldo B   (A permanece conectada)
  - Verifica: object_id diferente, saldos independentes, status independentes

Requer 2 contas (practice) — credenciais via variáveis de ambiente:
  IQOPTION_EMAIL_A / IQOPTION_PASSWORD_A
  IQOPTION_EMAIL_B / IQOPTION_PASSWORD_B

Execute: python scripts/test_multi_session.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


async def test_multi_session() -> None:
    from src.adapters.iqoption import IQOptionAdapter

    email_a = os.environ.get("IQOPTION_EMAIL_A")
    pass_a = os.environ.get("IQOPTION_PASSWORD_A")
    email_b = os.environ.get("IQOPTION_EMAIL_B")
    pass_b = os.environ.get("IQOPTION_PASSWORD_B")

    if not all([email_a, pass_a, email_b, pass_b]):
        print("ERRO: defina as 4 variaveis no .env:")
        print("  IQOPTION_EMAIL_A=...  IQOPTION_PASSWORD_A=...")
        print("  IQOPTION_EMAIL_B=...  IQOPTION_PASSWORD_B=...")
        return

    print("=" * 60)
    print("  TESTE MULTI-SESSAO IQ OPTION")
    print("=" * 60)

    adapter_a = IQOptionAdapter()
    adapter_b = IQOptionAdapter()

    # 1. Conectar conta A
    print("\n[1] Conectando conta A...")
    res_a = await adapter_a.connect({
        "email": email_a, "password": pass_a, "account_type": "practice",
    })
    print(f"    A: {res_a['status']}")

    # 2. Conectar conta B (A deve permanecer conectada)
    print("\n[2] Conectando conta B (A deve permanecer conectada)...")
    res_b = await adapter_b.connect({
        "email": email_b, "password": pass_b, "account_type": "practice",
    })
    print(f"    B: {res_b['status']}")

    # 3. Verificar que A ainda está conectada
    print("\n[3] Verificando status de A apos conectar B...")
    status_a = await adapter_a.get_status()
    status_b = await adapter_b.get_status()
    print(f"    A: {status_a['status']}")
    print(f"    B: {status_b['status']}")

    # 4. Saldos independentes
    print("\n[4] Consultando saldos...")
    bal_a = await adapter_a.get_balance()
    bal_b = await adapter_b.get_balance()
    print(f"    A: {bal_a.available} {bal_a.currency}")
    print(f"    B: {bal_b.available} {bal_b.currency}")

    # 5. object_id distintos (sessões WebSocket separadas)
    print("\n[5] Verificando object_id (sessao WebSocket)...")
    oid_a = getattr(adapter_a._api.api, "object_id", None) if adapter_a._api else None
    oid_b = getattr(adapter_b._api.api, "object_id", None) if adapter_b._api else None
    print(f"    A object_id: {oid_a}")
    print(f"    B object_id: {oid_b}")

    # 6. Candles independentes
    print("\n[6] Consultando candles em paralelo...")
    candles_a, candles_b = await asyncio.gather(
        adapter_a.get_candles("EURUSD", 1, 5),
        adapter_b.get_candles("EURUSD", 1, 5),
    )
    print(f"    A: {len(candles_a)} candles")
    print(f"    B: {len(candles_b)} candles")

    # Avaliacao
    print("\n" + "=" * 60)
    print("  RESULTADO")
    print("=" * 60)
    checks = {
        "A conectada apos conectar B": status_a.get("status") == "ready",
        "B conectada": status_b.get("status") == "ready",
        "object_id diferentes": oid_a is not None and oid_b is not None and oid_a != oid_b,
        "Ambas retornaram candles": len(candles_a) > 0 and len(candles_b) > 0,
        "Saldos consultados": bal_a is not None and bal_b is not None,
    }
    all_ok = True
    for name, ok in checks.items():
        mark = "OK " if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{mark}] {name}")

    # Desconectar
    print("\nDesconectando...")
    await adapter_a.disconnect()
    await adapter_b.disconnect()
    print("Pronto.")

    print("\n" + ("SUCESSO: multi-sessao funcionando!" if all_ok else "FALHA: verifique checks acima."))


if __name__ == "__main__":
    asyncio.run(test_multi_session())
