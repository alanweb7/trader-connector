"""Discrimina o fuso dos timestamps:(WIN dia inteiro) x relogio externo."""
import json, urllib.request, email.utils, collections
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
CONN = "e793ef85-ff1f-448d-bd4b-a029dc1f85ff"

print("=" * 64)
print("A) RELOGIO DA MAQUINA x INTERNET (header Date)")
print("=" * 64)
for u in ("https://www.google.com/", "https://github.com/", "https://httpbin.org/get"):
    try:
        req = urllib.request.Request(u, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            dh = r.headers.get("Date")
        ext = datetime(*email.utils.parsedate(dh)[:6], tzinfo=timezone.utc)
        print(f"  {u:30} -> {ext:%H:%M:%S} UTC")
    except Exception as e:
        print(f"  {u:30} -> falhou ({type(e).__name__})")
mach = datetime.now(timezone.utc)
print(f"  maquina                  -> {mach:%H:%M:%S} UTC  (BRT {datetime.now(BRT):%H:%M:%S})")

print()
print("=" * 64)
print("B) WIN M1 - janela por dia (lendo epoch como UTC e como BRT)")
print("=" * 64)
with urllib.request.urlopen(
    f"http://127.0.0.1:8000/connections/{CONN}/candles?asset=WIN&timeframe=1&count=1000",
    timeout=60,
) as r:
    cs = json.loads(r.read().decode())["candles"]

per = collections.defaultdict(list)
for x in cs:
    per[datetime.fromtimestamp(x["timestamp"], tz=timezone.utc).date()].append(x["timestamp"])

for day in sorted(per):
    ts = per[day]
    vu = [datetime.fromtimestamp(t, tz=timezone.utc) for t in ts]
    print(f"  {day}: {len(ts):4d} velas   "
          f"epoch-como-UTC {vu[0]:%H:%M}->{vu[-1]:%H:%M}   "
          f"(se epoch=BRT: mesmo; se epoch=UTC real BRT: "
          f"{vu[0].astimezone(BRT):%H:%M}->{vu[-1].astimezone(BRT):%H:%M})")

print()
print("=" * 64)
print("C) Ultima vela WIN x agora")
print("=" * 64)
last = cs[-1]["timestamp"]
lbl = datetime.fromtimestamp(last, tz=timezone.utc)
now = datetime.now(timezone.utc)
print(f"  ultima vela epoch-como-UTC: {lbl:%d/%m %H:%M}")
print(f"  agora UTC                 : {now:%d/%m %H:%M}")
print(f"  agora BRT                 : {datetime.now(BRT):%d/%m %H:%M}")
print(f"  defasagem (now - label)   : {(now.timestamp() - last)/60:.1f} min")
