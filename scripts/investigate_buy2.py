"""
Desvendar OP_code.ACTIVES, formato do ACTION e formato do expirations.
Teste de buy() com variações.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option, OP_code
import inspect

print("=" * 60)
print("INVESTIGAÇÃO: OP_code.ACTIVES, ACTION, EXPIRATIONS")
print("=" * 60)

# 1. Investigar OP_code
print("\n--- OP_code investigation ---")
print(f"OP_code type: {type(OP_code)}")
print(f"OP_code dir: {[x for x in dir(OP_code) if not x.startswith('_')]}")

if hasattr(OP_code, 'ACTIVES'):
    print("\nOP_code.ACTIVES:")
    actives = OP_code.ACTIVES
    print(f"  type: {type(actives)}")
    if isinstance(actives, dict):
        print(f"  keys count: {len(actives)}")
        # Mostrar alguns códigos
        for key in list(actives.keys())[:15]:
            print(f"    {key}: {actives[key]}")
        # Verificar se EURUSD existe
        if 'EURUSD' in actives:
            print(f"\n  EURUSD encontrado: {actives['EURUSD']}")
        else:
            print("\n  EURUSD NÃO encontrado em OP_code.ACTIVES")
            # Buscar similar
            similar = [k for k in actives.keys() if 'EUR' in k.upper()]
            print(f"  Similar com EUR: {similar}")

# 2. Investigar buyv3 e buyv3_by_raw_expired
print("\n--- API methods buyv3 and buyv3_by_raw_expired ---")
api = IQ_Option(EMAIL, PASSWORD)
api.connect()
print("connected")

if hasattr(api.api, 'buyv3'):
    print(f"\napi.api.buyv3 signature: {inspect.signature(api.api.buyv3)}")
    print(f"api.api.buyv3 source:")
    try:
        src = inspect.getsource(api.api.buyv3)
        for line in src.splitlines()[:30]:
            print(f"   {line}")
    except:
        print("  source unavailable")

if hasattr(api.api, 'buyv3_by_raw_expired'):
    print(f"\napi.api.buyv3_by_raw_expired signature: {inspect.signature(api.api.buyv3_by_raw_expired)}")
    print(f"api.api.buyv3_by_raw_expired source:")
    try:
        src = inspect.getsource(api.api.buyv3_by_raw_expired)
        for line in src.splitlines()[:30]:
            print(f"   {line}")
    except:
        print("  source unavailable")

# 3. Investigar get_expiration_time
print("\n--- get_expiration_time ---")
if 'get_expiration_time' in dir():
    print(f"get_expiration_time: {get_expiration_time}")
elif hasattr(api, 'get_expiration_time'):
    print(f"api.get_expiration_time: {inspect.signature(api.get_expiration_time)}")
    print(f"source:")
    try:
        src = inspect.getsource(api.get_expiration_time)
        for line in src.splitlines()[:30]:
            print(f"   {line}")
    except:
        print("  source unavailable")

# 4. Tentar conexão e testar buyv3 diretamente
print("\n--- Testando buyv3 diretamente ---")
try:
    ts = api.get_server_timestamp()
    print(f"server_timestamp: {ts}")
    
    # Testar com diferentes valores de ACTION e expirations
    test_cases = [
        ("1", 1),           # ACTION=1, expirations=1 minuto
        ("CALL", 1),        # ACTION=CALL, expirations=1 minuto  
        (1, 60),            # ACTION=1, expirations=60 segundos
        ("1", 60),          # ACTION=1, expirations=60 segundos
        ("CALL", 60),       # ACTION=CALL, expirations=60 segundos
        ("1", ts + 60),    # ACTION=1, expirations=timestamp absoluto
    ]
    
    for action, exp in test_cases:
        print(f"\n  Teste: ACTION={action!r}, expirations={exp!r}")
        try:
            # Precisa chamar buyv3 diretamente e ver o resultado
            api.api.buy_multi_option = {}
            api.api.buy_successful = None
            req_id = str(int(time.time() * 1000) % 100000)
            
            # Tentar chamar buyv3
            if hasattr(api.api, 'buyv3'):
                api.api.buyv3(1.0, OP_code.ACTIVES.get('EURUSD', 1), str(action), int(exp), req_id)
                start = time.time()
                result = None
                order_id = None
                while time.time() - start < 5:
                    try:
                        if 'message' in api.api.buy_multi_option.get(req_id, {}):
                            result = api.api.buy_multi_option[req_id]['message']
                            print(f"    Resultado (message): {result}")
                            break
                        if 'id' in api.api.buy_multi_option.get(req_id, {}):
                            order_id = api.api.buy_multi_option[req_id]['id']
                            result = api.api.result
                            print(f"    Resultado: {result}, ID: {order_id}")
                            break
                    except Exception as e:
                        pass
                    time.sleep(0.1)
                else:
                    print(f"    Timeout - result={api.api.result}, id={order_id}")
        except Exception as e:
            print(f"    Erro: {type(e).__name__}: {e}")

finally:
    # Desconectar
    if hasattr(api, 'logout'):
        try:
            api.logout()
        except:
            pass

print("\n" + "=" * 60)
print("INVESTIGAÇÃO CONCLUÍDA")
print("=" * 60)
