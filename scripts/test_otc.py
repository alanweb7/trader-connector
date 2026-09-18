"""
Investigar ativos OTC disponíveis e testar compra com eles.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option, OP_code

print("=" * 60)
print("INVESTIGAÇÃO DE ATIVOS OTC")
print("=" * 60)

actives = OP_code.ACTIVES

# 1. Listar todos os OTCs mapeados
otcs = [k for k in actives.keys() if 'OTC' in k]
print(f"\n OTCs mapeados em OP_code.ACTIVES ({len(otcs)}):")
for k in sorted(otcs):
    print(f"   {k}: código={actives[k]}")

# 2. Outros ativos relacionados a AUD
print(f"\n Ativos com AUD ({len([k for k in actives if 'AUD' in k])}):")
for k in sorted([k for k in actives if 'AUD' in k]):
    print(f"   {k}: código={actives[k]}")

# 3. Outros ativos forex
print(f"\n Ativos forex principais:")
forex_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'EURGBP', 'USDCHF', 'AUDCAD']
for pair in forex_pairs:
    if pair in actives:
        print(f"   {pair}: código={actives[pair]}")
    else:
        print(f"   {pair}: NÃO ENCONTRADO")

print("\n" + "=" * 60)
print("CONEXÃO PARA TESTE")
print("=" * 60)

api = IQ_Option(EMAIL, PASSWORD)
api.connect()
print(f"check_connect: {api.check_connect()}")
print(f"balance: {api.get_balance()}")
ts = api.get_server_timestamp()
print(f"server_timestamp: {ts}")

# 4. Testar compra com os OTCs disponíveis
print("\n" + "=" * 60)
print("TESTE DE COMPRA COM OTCs DISPONÍVEIS")
print("=" * 60)

tested = 0
success = 0

for asset in sorted(otcs):
    if asset not in actives:
        continue
    code = actives[asset]
    for action in ['CALL', 'PUT']:
        for exp in [1, 2]:
            print(f"\nbuy(1, {asset!r}, {action!r}, {exp})...")
            try:
                api.api.buy_multi_option = {}
                api.api.buy_successful = None
                req_id = str(int(time.time() * 1000) % 100000)
                
                api.api.buyv3(1.0, code, action, exp, req_id)
                
                t0 = time.time()
                res = None
                oid = None
                while time.time() - t0 < 4:
                    try:
                        d = api.api.buy_multi_option.get(req_id, {})
                        if 'message' in d:
                            res = d['message']
                            break
                        if 'id' in d:
                            oid = d['id']
                            res = api.api.result
                            break
                    except:
                        pass
                    time.sleep(0.1)
                
                tested += 1
                if oid:
                    success += 1
                    print(f"  ✓ SUCESSO! id={oid}, result={res}")
                else:
                    msg_short = (res[:100] if res and isinstance(res, str) else str(res))
                    print(f"  ✗ FALHA: {msg_short}")
                    
            except Exception as e:
                print(f"  ERRO: {type(e).__name__}: {e}")

print(f"\n{'='*60}")
print(f"RESUMO: {success}/{tested} ordens aceitas")
print(f"{'='*60}")

# 5. Investigar buy_by_raw_expirations para OTC
print("\n" + "=" * 60)
print("TESTE buy_by_raw_expirations COM OTC")
print("=" * 60)

if hasattr(api, 'buy_by_raw_expired'):
    print(f"buy_by_raw_expired signature: {inspect.signature(api.buy_by_raw_expired)}")
    
    for asset in sorted(otcs)[:3]:  # só os 3 primeiros
        if asset not in actives:
            continue
        code = actives[asset]
        for direction in ['CALL', 'PUT']:
            for exp in [1, 2]:
                print(f"\nbuy_by_raw_expired(1, {asset!r}, {direction!r}, {exp}, ts+{exp*60})...")
                try:
                    api.api.buy_multi_option = {}
                    api.api.buy_successful = None
                    req_id = "raw_" + str(int(time.time() * 1000) % 100000)
                    
                    api.api.buyv3_by_raw_expired(
                        1.0, code, direction, exp, ts + exp*60, req_id
                    )
                    
                    t0 = time.time()
                    res = None
                    oid = None
                    while time.time() - t0 < 4:
                        try:
                            d = api.api.buy_multi_option.get(req_id, {})
                            if 'message' in d:
                                res = d['message']
                                break
                            if 'id' in d:
                                oid = d['id']
                                res = api.api.result
                                break
                        except:
                            pass
                        time.sleep(0.1)
                    
                    if oid:
                        print(f"  ✓ SUCESSO! id={oid}, result={res}")
                    else:
                        print(f"  ✗ FALHA: {res}")
                except Exception as e:
                    print(f"  ERRO: {type(e).__name__}: {e}")

# 6. Investigar métodos alternativos
print("\n" + "=" * 60)
print("INVESTIGA MÉTODOS ALTERNATIVOS")
print("=" * 60)

# Verificar se existe método para digital OTC
methods = [m for m in dir(api) if 'otc' in m.lower() or 'digital' in m.lower()]
print(f"Métodos com 'otc' ou 'digital': {methods}")

# Verificar buy_digital_spot com ativos OTC
if hasattr(api, 'buy_digital_spot'):
    print(f"\nbuy_digital_spot signature: {inspect.signature(api.buy_digital_spot)}")
    print("Testando buy_digital_spot com pré-oxford...")
    for asset in ['EURUSD-OTC']:  # apenas um para teste
        for action in ['CALL', 'PUT']:
            for duration in [1, 2]:
                print(f"\n  buy_digital_spot({asset!r}, 1, {action!r}, {duration})...")
                try:
                    ok, oid = api.buy_digital_spot(asset, 1, action, duration)
                    print(f"    Result: ok={ok}, id={oid}")
                    if oid:
                        success += 1
                        tested += 1
                except Exception as e:
                    print(f"    Erro: {type(e).__name__}: {e}")

# 7. Sair
print("\n" + "=" * 60)
print("FIM")
print("=" * 60)
try:
    api.logout()
    print("logout executado")
except Exception as e:
    print(f"logout error: {e}")
