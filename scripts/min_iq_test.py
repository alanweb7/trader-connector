"""Teste mínimo possível."""
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

print("get_all_open_time...")
import signal
def handler(signum, frame):
    raise TimeoutError("timeout")
signal.signal(signal.SIGALRM, handler)
signal.alarm(8)
try:
    aos = api.get_all_open_time()
    signal.alarm(0)
    print("result type:", type(aos).__name__)
    if isinstance(aos, dict):
        print("keys:", list(aos.keys())[:12])
except TimeoutError:
    print("TIMEOUT")
finally:
    signal.alarm(0)
