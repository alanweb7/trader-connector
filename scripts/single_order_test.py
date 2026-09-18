"""
1 ordem, 1 minuto, AUDCAD-OTC. Captura resultado final.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option, OP_code

AUDCAD_OTC = OP_code.ACTIVES['AUDCAD-OTC']  # 86

api = IQ_Option(EMAIL, PASSWORD)
print("connect...")
api.connect()
print(f"check_connect: {api.check_connect()}")
print(f"balance: {api.get_balance()}")
print(f"server_ts: {api.get_server_timestamp()}")

# 1 ordem: estratégia simples - usa CALL ou PUT baseado no relógio
import time as _time
direction = "CALL" if int(_time.time()) % 2 == 0 else "PUT"
exp = 1
amount = 1

print(f"\nbuy(1, 'AUDCAD-OTC', {direction}, {exp}min)...")
api.api.buy_multi_option = {}
api.api.buy_successful = None
req_id = str(int(_time.time() * 1000) % 100000)

t0 = _time.time()
api.api.buyv3(amount, AUDCAD_OTC, direction, exp, req_id)

order_id = None
result = None
while _time.time() - t0 < 5:
    try:
        d = api.api.buy_multi_option.get(req_id, {})
        if 'message' in d:
            result = d['message']
            break
        if 'id' in d:
            order_id = d['id']
            result = api.api.result
            break
    except:
        pass
    _time.sleep(0.1)

print(f"retorno em {_time.time()-t0:.2f}s")
if order_id:
    print(f"ORDEM ACEITA: id={order_id}, result={result}")
else:
    print(f"FALHA: {result}")
    raise SystemExit(1)

print(f"\nAguardando {exp} minuto(s) + buffer para expiração...")
# Aguarda a expiração da ordem (1 minuto) + 30s buffer
_time.sleep(exp * 60 + 30)

print("\nVerificando resultado...")
methods = [
    'check_win',
    'check_win_v2', 
    'check_win_v3',
    'check_win_v4',
    'check_binary_order',
]

for method in methods:
    if not hasattr(api, method):
        continue
    try:
        resp = getattr(api, method)(order_id)
        print(f"{method}(order_id): {resp}")
    except Exception as e:
        print(f"{method}(order_id): erro - {type(e).__name__}: {e}")

# Tenta também get_betinfo
try:
    ok, info = api.get_betinfo(order_id)
    print(f"get_betinfo: ok={ok}, info={info}")
except Exception as e:
    print(f"get_betinfo: erro - {e}")

print("\nFim do teste.")
try:
    api.logout()
except:
    pass
