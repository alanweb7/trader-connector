"""Teste síncrono, passo a passo, sem threads extras."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option

def step(label, fn, *args, **kw):
    print(f"\n[{label}]")
    try:
        r = fn(*args, **kw)
        print(f"  ok: {r!r}" if not isinstance(r, (list, dict)) or len(str(r)) < 300 else f"  ok: {type(r).__name__} len={len(r)}")
        return r
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None

api = IQ_Option(EMAIL, PASSWORD)
step("connect", api.connect)
time.sleep(1)
step("check_connect", api.check_connect)
step("get_balance", api.get_balance)

aos = step("get_all_open_time", api.get_all_open_time)
if isinstance(aos, dict):
    print("  keys:", list(aos.keys()))
    for section in ("turbo", "binary", "digital", "forex", "crypto"):
        if section in aos and isinstance(aos[section], dict):
            syms = list(aos[section].keys())
            print(f"  [{section}] count={len(syms)}")
            for s in syms[:5]:
                print(f"    {s}: {aos[section][s]}")

ts = step("get_server_timestamp", api.get_server_timestamp)
step("get_candles EURUSD 60x3", api.get_candles, "EURUSD", 60, 3, ts)

print("\n[fim] desconectando...")
try:
    api.disconnect()
    print("  desconectado")
except Exception as e:
    print("  disconnect:", e)
print("[fim]")
