"""
Mais um teste: 1 ordem de compra 1min, AUDCAD-OTC, resultado via check_win_v4 (sem polling infinito).
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"
from iqoptionapi.stable_api import IQ_Option, OP_code

API = IQ_Option(EMAIL, PASSWORD)
AUDCAD_OTC = OP_code.ACTIVES["AUDCAD-OTC"]

print(f"Conn+status+balance")
API.connect()
print(f"check_connect: {API.check_connect()}")
print(f"balance: {API.get_balance()}")

direction = "CALL" if int(time.time()) % 2 == 0 else "PUT"
exp = 1
amount = 1
print(f"\nbuy({amount}, AUDCAD-OTC, {direction}, {exp}min)...")

API.api.buy_multi_option = {}
API.api.buy_successful = None
req_id = str(int(time.time() * 1000) % 100000)
t0 = time.time()
API.api.buyv3(amount, AUDCAD_OTC, direction, exp, req_id)

oid = None
res = None
while time.time() - t0 < 5:
    try:
        d = API.api.buy_multi_option.get(req_id, {})
        if "message" in d:
            res = d["message"]
            break
        if "id" in d:
            oid = d["id"]
            res = API.api.result
            break
    except Exception:
        pass
    time.sleep(0.1)

print(f"retorno em {time.time()-t0:.2f}s")
if not oid:
    print(f"FALHA NA ORDEM: {res}")
    raise SystemExit(1)

print(f"ORDEM: id={oid}, dir={direction}, ativo=AUDCAD-OTC, exp={exp}min, status aceite={res}")

print("\nAguardando expiracao...")
time.sleep(exp * 60 + 10)

print("\nCapturando resultado (check_win_v4, sem espera infinita)...")
try:
    resultado = API.check_win_v4(oid)
    print(f"RESULTADO: {resultado}")
except Exception as e:
    print(f"check_win_v4 falhou: {type(e).__name__}: {e}")

print("\nlogout")
try:
    API.logout()
except Exception:
    pass
print("fim")
