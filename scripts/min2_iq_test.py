"""Teste minimo: connect, check, balance, e tentativa curta de get_all_open_time."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option

api = IQ_Option(EMAIL, PASSWORD)

print("connect...")
api.connect()
print("check:", api.check_connect())
print("balance:", api.get_balance())

print("get_all_open_time (esperando ate 12s)...")
t0 = time.time()
aos = api.get_all_open_time()
dt = time.time() - t0
print(f"  retorno em {dt:.1f}s, tipo={type(aos).__name__}")
if isinstance(aos, dict):
    print("  keys:", list(aos.keys())[:12])
    for section in ("turbo", "binary", "digital", "forex", "crypto"):
        if section in aos and isinstance(aos[section], dict):
            syms = list(aos[section].keys())
            print(f"  [{section}] count={len(syms)}")
            for s in syms[:5]:
                print(f"    {s}: {aos[section][s]}")
else:
    print("  valor:", aos)
