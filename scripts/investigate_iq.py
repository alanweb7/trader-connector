"""Dissecar get_all_open_time: qual thread/evento/lock bloqueia."""
import sys, os, time, inspect, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"
from iqoptionapi.stable_api import IQ_Option

api = IQ_Option(EMAIL, PASSWORD)
api.connect()
print("check_connect:", api.check_connect())
print("balance:", api.get_balance())

print("\n--- get_all_open_time signature:", inspect.signature(api.get_all_open_time))
print("--- get_all_open_time source (primeiras 40 linhas):")
print(inspect.getsource(api.get_all_open_time)[:1500])

print("\n--- atributos do objeto api que parecem locks/eventos/threading ---")
for attr_name in dir(api):
    if any(k in attr_name.lower() for k in ["event", "lock", "thread", "cond", "queue", "barrier", "semaphore"]):
        try:
            val = getattr(api, attr_name)
            print(f"  {attr_name} = {type(val).__name__}", end="")
            if hasattr(val, '__self__'):
                print(f" (thread: {getattr(val.__self__, 'name', '?')})", end="")
            if isinstance(val, threading.Event):
                print(f" is_set={val.is_set()}", end="")
            if isinstance(val, (threading.Lock, threading.RLock)):
                print(" (lock)", end="")
            print()
        except Exception as e:
            print(f"  {attr_name} = <erro: {e}>")

print("\n--- threads ativas no processo ---")
for t in threading.enumerate():
    print(f"  {t.name} (daemon={t.daemon}, alive={t.is_alive()})")

print("\n--- get_all_open_time com timeout via thread ---")
def call_it():
    global AOS
    t_in = time.time()
    try:
        AOS = api.get_all_open_time()
        dt = time.time() - t_in
        print(f"  get_all_open_time retorno em {dt:.1f}s; tipo={type(AOS).__name__}")
        if isinstance(AOS, dict):
            print(f"  keys={list(AOS.keys())[:12]}")
    except Exception as e:
        dt = time.time() - t_in
        print(f"  get_all_open_time falhou em {dt:.1f}s: {type(e).__name__}: {e}")

AOS = None
t = threading.Thread(target=call_it, name="caller")
t.start()
t.join(timeout=10)
if t.is_alive():
    print("  [!] get_all_open_time continua rodando apos 10s; threads ativas:")
    for th in threading.enumerate():
        print(f"    - {th.name} alive={th.is_alive()} daemon={th.daemon}")
    print("  [!] threads do api:", [n for n in dir(api) if 'thread' in n.lower()])
else:
    print("  [v] get_all_open_time terminou dentro do timeout")

print("\n--- tentativa de entender gevent/asyncio/threading mix na lib ---")
try:
    print("has _thread:", hasattr(api, '_thread'))
    print("_thread type:", type(getattr(api, '_thread', None)))
except Exception as e:
    print("erro:", e)

print("\n[fim] desconectando...")
api.disconnect()
print("desconectado")
