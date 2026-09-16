"""
Teste de ordem direto com EURUSD - opção 1
Fluxo: conectar → saldo → buy(EURUSD) → resultado
ATENÇÃO: executa ordem REAL em conta de prática.
Execute apenas com autorização explícita.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"

from iqoptionapi.stable_api import IQ_Option

print("=" * 60)
print("TESTE DE ORDEM DIRETO - IQ Option (prática)")
print("=" * 60)
print(f"Email: {EMAIL}")
print(f"Conta: practice")
print(f"Ativo: EURUSD")
print(f"Operação: CALL 1 unidade, 1 minuto")
print("=" * 60)
print()

api = IQ_Option(EMAIL, PASSWORD)

try:
    # 1. Conectar
    print("[1] Conectando...")
    api.connect()
    print(f"    check_connect: {api.check_connect()}")

    # 2. Saldo
    print("[2] Saldo:")
    bal = api.get_balance()
    print(f"    {bal} (prática = 10.000)")

    # 3. Timestamp
    print("[3] Timestamp do servidor:")
    ts = api.get_server_timestamp()
    print(f"    {ts}")

    # 4. ORDER REAL
    print("[4] Enviando ordem: buy(1, 'EURUSD', 1, 1)")
    print("    (CALL, 1 unidade, 1 minuto)")
    t0 = time.time()
    result = api.buy(1, "EURUSD", 1, 1)
    dt = time.time() - t0
    print(f"    buy() retornou em {dt:.2f}s")
    print(f"    resultado: {result}")

    if result and result[0]:
        order_id = result[1]
        print(f"    ID da ordem: {order_id}")
        print()
        print("[5] Aguardando resultado do trade (poller 60s)...")

        for i in range(60):
            time.sleep(1)
            try:
                # Verificar resultado
                trade_info = api.check_win(order_id)
                print(f"    [{i+1}s] check_win: {trade_info}")
                if trade_info and isinstance(trade_info, dict):
                    if "win" in trade_info or "profit" in trade_info:
                        print(f"    RESULTADO: {trade_info}")
                        break
            except Exception as e:
                print(f"    [{i+1}s] check_win error: {e}")

            # Também tentar get_position / get_positions
            try:
                if hasattr(api, 'get_position'):
                    pos = api.get_position()
                    if pos:
                        print(f"    [{i+1}s] get_position: {pos}")
                if hasattr(api, 'get_positions'):
                    pos = api.get_positions()
                    if pos:
                        print(f"    [{i+1}s] get_positions: {pos}")
            except Exception:
                pass
    else:
        print("    Ordem recusada ou resultado vazio")

    # 5. Desconectar
    print()
    print("[6] Desconectando...")
    # A lib pode não ter disconnect - usar logout ou finalize
    for method in ['disconnect', 'logout', 'close']:
        if hasattr(api, method):
            try:
                getattr(api, method)()
                print(f"    {method}() executado")
                break
            except Exception as e:
                print(f"    {method}() error: {e}")
    else:
        print("    Nenhum método de desconexão encontrado")

    print()
    print("=" * 60)
    print("TESTE FINALIZADO")
    print("=" * 60)

except Exception as e:
    print(f"\n[ERRO] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
