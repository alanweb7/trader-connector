"""Teste síncrono e curto de conexão IQ Option."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"

from iqoptionapi.stable_api import IQ_Option

api = IQ_Option(EMAIL, PASSWORD)

try:
    print("[1] Conectando...")
    api.connect()
    print("[2] check_connect():", api.check_connect())
    time.sleep(3)

    print("[3] get_balance():", api.get_balance())

    print("[4] get_all_open_time:")
    aos = api.get_all_open_time()
    print("    type:", type(aos).__name__)
    if isinstance(aos, dict):
        print("    keys:", list(aos.keys())[:12])
        if "turbo" in aos and isinstance(aos["turbo"], dict):
            syms = list(aos["turbo"].keys())
            print("    turbo ativos:", len(syms))
            for s in syms[:8]:
                d = aos["turbo"][s]
                print(f"      {s}: payout={d.get('payout','?')}, open={d.get('open','?')}")

    print("[5] server_timestamp:", api.get_server_timestamp())

    print("[6] get_candles(EURUSD,60,3,ts):")
    c = api.get_candles("EURUSD", 60, 3, api.get_server_timestamp())
    print("    count:", len(c) if c else 0)
    if c:
        print("    latest:", c[-1].get("open"), c[-1].get("close"))

    print("[7] buy(1,'EURUSD',1,1):")
    res = api.buy(1, "EURUSD", 1, 1)
    print("    result:", res)

finally:
    print("[X] Desconectando...")
    try:
        api.disconnect()
    except Exception as e:
        print("    disconnect err:", e)
    print("[X] Feito.")
