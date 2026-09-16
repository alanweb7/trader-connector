"""
1 ordem AUDCAD-OTC 1min com captura de resultado via polling com timeout.
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"
from iqoptionapi.stable_api import IQ_Option, OP_code

AUDCAD_OTC = OP_code.ACTIVES['AUDCAD-OTC']  # 86
api = IQ_Option(EMAIL, PASSWORD)

print("connect...")
api.connect()
print(f"check_connect: {api.check_connect()}")
print(f"balance: {api.get_balance()}")

direction = "CALL" if int(time.time()) % 2 == 0 else "PUT"
exp = 1
amount = 1
print(f"\nbuy(1, 'AUDCAD-OTC', {direction}, {exp}min)...")

api.api.buy_multi_option = {}
api.api.buy_successful = None
req_id = str(int(time.time() * 1000) % 100000)
t0 = time.time()
api.api.buyv3(amount, AUDCAD_OTC, direction, exp, req_id)

order_id = None
result = None
while time.time() - t0 < 5:
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
    time.sleep(0.1)

print(f"retorno em {time.time()-t0:.2f}s")
if not order_id:
    print(f"FALHA: {result}")
    raise SystemExit(1)

print(f"ORDEM ACEITA: id={order_id}")
print(f"Aguardando {exp}min + 15s para expiração...")
time.sleep(exp * 60 + 15)

print("\nCapturando resultado com polling (timeout 10s por método)...")

def poll_with_timeout(fn, label, timeout=10):
    """Executa fn em thread separada com timeout."""
    err = None
    resp = [None]
    def target():
        try:
            resp[0] = fn()
        except Exception as e:
            resp[0] = f"ERROR: {type(e).__name__}: {e}"
    
    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return f"TIMEOUT after {timeout}s"
    return resp[0]

methods_to_try = [
    ('check_win', lambda: api.check_win(order_id)),
    ('check_win_v2', lambda: api.check_win_v2(order_id)),
    ('check_win_v3', lambda: api.check_win_v3(order_id)),
    ('check_win_v4', lambda: api.check_win_v4(order_id)),
    ('check_binary_order', lambda: api.check_binary_order(order_id)),
]

for name, fn in methods_to_try:
    r = poll_with_timeout(fn, name, timeout=10)
    print(f"  {name}: {r}")

# get_betinfo com timeout
try:
    r = poll_with_timeout(lambda: api.get_betinfo(order_id), 'get_betinfo', timeout=10)
    print(f"  get_betinfo: {r}")
except Exception as e:
    print(f"  get_betinfo: erro - {e}")

print("\nFim.")
try:
    api.logout()
except:
    pass
