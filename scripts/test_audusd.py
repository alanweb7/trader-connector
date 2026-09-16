"""
Testar compra com AUDUSD-OTC na IQ Option prática.
Investiga AUDUSD em OP_code.ACTIVES + testa buy() com ACTION=CALL/PUT e variações de expiration.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"

from iqoptionapi.stable_api import IQ_Option, OP_code
import inspect

print("=" * 60)
print("TESTE COM AUDUSD-OTC - IQ Option (prática)")
print("=" * 60)
print()

# 1. Investigar AUDUSD em OP_code.ACTIVES
print("--- OP_code.ACTIVES ---")
actives = OP_code.ACTIVES
print(f"Total de ativos mapeados: {len(actives)}")

# Buscar AUDUSD
if 'AUDUSD' in actives:
    print(f"AUDUSD encontrado: código={actives['AUDUSD']}")
else:
    print("AUDUSD NÃO encontrado em OP_code.ACTIVES")
    # Similar
    similar = [k for k in actives.keys() if 'AUD' in k.upper()]
    print(f"Ativos com AUD: {similar}")
    similar2 = [k for k in actives.keys() if 'USD' in k.upper()][-10:]
    print(f"Ativos com USD (últimos 10): {similar2}")

print()

# 2. Conectar
api = IQ_Option(EMAIL, PASSWORD)
print("[1] Conectando...")
api.connect()
print(f"    check_connect: {api.check_connect()}")

# 3. Saldo
print("[2] Saldo:")
bal = api.get_balance()
print(f"    {bal}")

# 4. Timestamp
ts = api.get_server_timestamp()
print(f"[3] Timestamp servidor: {ts}")

# 5. Testar buy() com variações
print("\n[4] Testando buy() com variações de parâmetro...")

# AUDUSD pode ser "AUDUSD" ou "AUDUSD-OTC" dependendo do tipo de opção
test_assets = ['AUDUSD', 'AUDUSD-OTC']
test_actions = ['CALL', 'PUT']
test_expirations = [1, 2, 5]  # minutos

results = []
for asset in test_assets:
    for action in test_actions:
        for exp in test_expirations:
            print(f"\n  buy(1, {asset!r}, {action!r}, {exp})...")
            try:
                api.api.buy_multi_option = {}
                api.api.buy_successful = None
                req_id = str(int(time.time() * 1000) % 100000)
                
                # Resolver código do ativo
                active_code = OP_code.ACTIVES.get(asset, None)
                if active_code is None:
                    print(f"    ATIVO NÃO MAPEADO: {asset}")
                    continue
                
                api.api.buyv3(1.0, active_code, action, exp, req_id)
                
                start = time.time()
                result = None
                order_id = None
                while time.time() - start < 5:
                    try:
                        d = api.api.buy_multi_option.get(req_id, {})
                        if 'message' in d:
                            result = d['message']
                            print(f"    Resposta: {result[:200]}")
                            break
                        if 'id' in d:
                            order_id = d['id']
                            result = api.api.result
                            print(f"    SUCESSO! Result: {result}, ID: {order_id}")
                            break
                    except:
                        pass
                    time.sleep(0.1)
                else:
                    print(f"    Timeout (5s). api.result={api.api.result}, id={order_id}")
                
                results.append((asset, action, exp, result, order_id))
                
            except Exception as e:
                print(f"    Erro: {type(e).__name__}: {e}")
                results.append((asset, action, exp, str(e), None))

print("\n[5] Resumo dos resultados:")
print("-" * 60)
for asset, action, exp, result, oid in results:
    status = "✓ SUCESSO" if oid else "✗ FALHA"
    print(f"  {status} | {asset:12s} | {action:5s} | exp={exp:2d} | {str(result)[:80]}")

# 6. Tentar buy_by_raw_expirations se houver
print("\n[6] Testando buy_by_raw_expirations...")
try:
    if hasattr(api, 'buy_by_raw_expired'):
        print(f"  buy_by_raw_expired signature: {inspect.signature(api.buy_by_raw_expired)}")
        # Testar com formatos diferentes
        for asset in ['AUDUSD']:
            if asset not in OP_code.ACTIVES:
                continue
            active_code = OP_code.ACTIVES[asset]
            for direction in ['CALL', 'PUT']:
                for exp in [1, 2]:
                    print(f"\n  buy_by_raw_expired(1, {asset}, {direction}, {exp}, ...)")
                    try:
                        api.api.buy_multi_option = {}
                        api.api.buy_successful = None
                        req_id = "raw_" + str(int(time.time() * 1000) % 100000)
                        
                        api.api.buyv3_by_raw_expired(
                            1.0, active_code, direction, exp, ts + exp*60, req_id
                        )
                        
                        start = time.time()
                        while time.time() - start < 5:
                            try:
                                d = api.api.buy_multi_option.get(req_id, {})
                                if 'message' in d:
                                    print(f"    Resposta: {d['message'][:200]}")
                                    break
                                if 'id' in d:
                                    print(f"    SUCESSO! ID: {d['id']}, Result: {api.api.result}")
                                    break
                            except:
                                pass
                            time.sleep(0.1)
                        else:
                            print(f"    Timeout. result={api.api.result}")
                    except Exception as e:
                        print(f"    Erro: {type(e).__name__}: {e}")
except Exception as e:
    print(f"  Erro: {e}")

# 7. Tentar digital spot (para opções digitais)
print("\n[7] Testando buy_digital_spot...")
try:
    if hasattr(api, 'buy_digital_spot'):
        print(f"  buy_digital_spot signature: {inspect.signature(api.buy_digital_spot)}")
        for action in ['CALL', 'PUT']:
            for duration in [1, 2]:
                print(f"\n  buy_digital_spot('AUDUSD', 1, {action!r}, {duration})...")
                try:
                    ok, oid = api.buy_digital_spot('AUDUSD', 1, action, duration)
                    print(f"    Result: ok={ok}, id={oid}")
                except Exception as e:
                    print(f"    Erro: {type(e).__name__}: {e}")
except Exception as e:
    print(f"  Erro: {e}")

# 8. Desconexão
print("\n[8] Desconectando...")
try:
    api.logout()
    print("    logout() executado")
except Exception as e:
    print(f"    logout error: {e}")

print("\n" + "=" * 60)
print("TESTE CONCLUÍDO")
print("=" * 60)
