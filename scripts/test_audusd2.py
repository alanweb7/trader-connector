"""Teste enxuto com AUDUSD / OTC - timeout curto por chamada."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"
from iqoptionapi.stable_api import IQ_Option, OP_code

print("OP_code.ACTIVES 'AUDUSD':", 'AUDUSD' in OP_code.ACTIVES, OP_code.ACTIVES.get('AUDUSD'))
print("OP_code.ACTIVES keys com AUD:", [k for k in OP_code.ACTIVES if 'AUD' in k][:10])
print("OP_code.ACTIVES keys com OTC:", [k for k in OP_code.ACTIVES if 'OTC' in k][:10])

api = IQ_Option(EMAIL, PASSWORD)
print("\nconnect...")
api.connect()
print("check:", api.check_connect())
print("balance:", api.get_balance())
ts = api.get_server_timestamp()
print("server_ts:", ts)

# Testes curtos
for asset in ['AUDUSD', 'AUDUSD-OTC']:
    if asset not in OP_code.ACTIVES:
        print(f"\n{asset}: NÃO está em OP_code.ACTIVES")
        continue
    code = OP_code.ACTIVES[asset]
    for action in ['CALL', 'PUT']:
        for exp in [1, 2, 5]:
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
                print(f"  retorno em {time.time()-t0:.1f}s; id={oid}; result={res}")
                if res and isinstance(res, str) and len(res) > 150:
                    print(f"  msg: {res[:150]}")
            except Exception as e:
                print(f"  ERRO: {type(e).__name__}: {e}")

print("\nlogout...")
try:
    api.logout()
except Exception as e:
    print("logout err:", e)
print("fim")
