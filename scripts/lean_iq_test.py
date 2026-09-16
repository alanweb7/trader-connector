"""
Teste enxuto: conectar, validar, obter dados basicos, desconectar.
Executar: python scripts/lean_iq_test.py
"""
import sys
import os
import time
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"

from iqoptionapi.stable_api import IQ_Option

RESULT = {}
ERROR = None

def run():
    global ERROR
    api = None
    try:
        api = IQ_Option(EMAIL, PASSWORD)
        print("[1] connect()...")
        t0 = time.time()
        api.connect()
        dt = time.time() - t0
        print(f"    connect() levou {dt:.1f}s")
        print(f"    check_connect() = {api.check_connect()}")

        print("[2] get_balance()...")
        bal = api.get_balance()
        print(f"    saldo = {bal}")

        print("[3] get_all_open_time()...")
        aos = api.get_all_open_time()
        print(f"    tipo = {type(aos).__name__}")
        if isinstance(aos, dict):
            print(f"    keys = {list(aos.keys())}")
            if "turbo" in aos and isinstance(aos["turbo"], dict):
                syms = list(aos["turbo"].keys())
                print(f"    turbo ativos = {len(syms)}")
                for s in syms[:8]:
                    d = aos["turbo"][s]
                    print(f"      {s}: payout={d.get('payout','?')}, open={d.get('open','?')}")

        print("[4] get_server_timestamp()...")
        ts = api.get_server_timestamp()
        print(f"    timestamp = {ts}")

        print("[5] get_candles(EURUSD,60,3,ts)...")
        c = api.get_candles("EURUSD", 60, 3, ts)
        print(f"    count = {len(c) if c else 0}")
        if c:
            cc = c[-1]
            print(f"    latest: open={cc.get('open')}, close={cc.get('close')}")

        print("[6] OK - desconectando...")
        api.disconnect()
        print("[7] Desconectado.")
        RESULT["ok"] = True
    except Exception as e:
        ERROR = traceback.format_exc()
        print(f"[ERRO] {e}")
        if api:
            try:
                api.disconnect()
            except Exception:
                pass

t = threading.Thread(target=run, daemon=True)
t.start()
t.join(timeout=45)

if t.is_alive():
    print("\n[!] Thread ainda em execucao apos 45s - possivel travamento.")
    print("[!] Resultado parcial:")
    print(f"    RESULT = {RESULT}")
    if ERROR:
        print(f"    ERROR (parcial) = {ERROR[:500]}")
else:
    print(f"\n[+] Thread concluida.")
    print(f"    RESULT = {RESULT}")
    if ERROR:
        print(f"    ERROR = {ERROR}")
