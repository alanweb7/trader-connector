"""Compara relogoio real BRT x timestamp da ultima vela x janela de sessao B3."""
import json, urllib.request
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
CONN = "e793ef85-ff1f-448d-bd4b-a029dc1f85ff"

now_local = datetime.now(BRT)
print("agora REAL (BRT):", now_local.strftime("%d/%m/%Y %H:%M:%S"))

try:
    with urllib.request.urlopen("http://127.0.0.1:8001/api/v1/b3-session", timeout=15) as r:
        print("b3_session_status:", r.read().decode()[:500])
except Exception as e:
    print("b3_session_status ERRO:", e)

with urllib.request.urlopen(
    f"http://127.0.0.1:8000/connections/{CONN}/candles?asset=BIT&timeframe=1&count=3",
    timeout=30,
) as r:
    c = json.loads(r.read().decode())["candles"]

print("\nUltimas 3 velas:")
for x in c:
    t = datetime.fromtimestamp(x["timestamp"], tz=timezone.utc)
    print(f"  epoch={x['timestamp']}  UTC={t:%H:%M}  "
          f"BRT(convertido)={t.astimezone(BRT):%H:%M}  C={x['close']}")

last = c[-1]["timestamp"]
lag = (now_local.timestamp() - last) / 60
last_brt = datetime.fromtimestamp(last, tz=timezone.utc).astimezone(BRT)
print(f"\nagora BRT ............: {now_local:%H:%M}")
print(f"ultima vela (BRT) ....: {last_brt:%H:%M}  -> defasagem {lag:.1f} min")
print(f"ultima vela (UTC) ....: {datetime.fromtimestamp(last, tz=timezone.utc):%H:%M}")
print(f"se epoch for BRT crus : {datetime.fromtimestamp(last):%H:%M} (tratando epoch como hora local)")
