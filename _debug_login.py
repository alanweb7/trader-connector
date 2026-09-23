"""Diagnóstico: UMA tentativa de login crua com prints completos."""
import os, sys, time

if not os.environ.get('IQOPTION_EMAIL') or not os.environ.get('IQOPTION_PASSWORD'):
    raise SystemExit('Defina IQOPTION_EMAIL e IQOPTION_PASSWORD.')

sys.path.insert(0, os.path.abspath('.'))
import iqoptionapi.global_value as gv
from iqoptionapi.stable_api import IQ_Option

api = IQ_Option(os.environ['IQOPTION_EMAIL'], os.environ['IQOPTION_PASSWORD'])
print('CHAMANDO connect() ...', flush=True)
t0 = time.time()
try:
    ok, reason = api.connect()
    print(f'RESULT em {time.time()-t0:.1f}s: ok={ok!r} reason={reason!r}', flush=True)
except Exception as e:
    print(f'connect EXC: {type(e).__name__}: {e!r}', flush=True)

print('check_connect:', api.check_connect(), flush=True)
print('SSID:', gv.SSID, flush=True)
os._exit(0)
