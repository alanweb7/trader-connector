"""Consolida: vela 10:37 BRT, histograma de horas e interpretacoes."""
import json, urllib.request, collections
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
CONN = "e793ef85-ff1f-448d-bd4b-a029dc1f85ff"
EPOCH_1037 = 1793702220  # 03/11 10:37 (label = BRT)


def lbl(e):        # como os dados "marcam" (epoch lido como UTC) = hora real BRT
    return datetime.fromtimestamp(e, tz=timezone.utc)


def naive(e):      # conversao ingenua (epoch -> hora local BRT) = 3h atras
    return datetime.fromtimestamp(e)


print("=" * 66)
print("A) VELA 10:37 DE HOJE (03/11) - WIN e BIT")
print("=" * 66)
for asset in ("WIN", "BIT"):
    with urllib.request.urlopen(
        f"http://127.0.0.1:8000/connections/{CONN}/candles"
        f"?asset={asset}&timeframe=1&count=200", timeout=40) as r:
        cs = json.loads(r.read().decode())["candles"]
    hits = [x for x in cs if lbl(x["timestamp"]).hour == 10
            and lbl(x["timestamp"]).minute == 37
            and lbl(x["timestamp"]).date().isoformat() == "2026-11-03"]
    for x in hits:
        i = cs.index(x)
        print(f"\n  {asset}  epoch={x['timestamp']}  "
              f"(exibido ingenuamente: {naive(x['timestamp']):%H:%M})")
        for j in range(max(0, i - 1), min(len(cs), i + 2)):
            y = cs[j]
            m = "   <== 10:37 BRT" if j == i else ""
            print(f"    {lbl(y['timestamp']):%H:%M}  O={y['open']:>9}  H={y['high']:>9}  "
                  f"L={y['low']:>9}  C={y['close']:>9}  V={y['volume']}{m}")
        dlt = x["close"] - x["open"]
        print(f"    fechamento vs abertura: {dlt:+g} "
              f"({dlt / x['open'] * 100:+.3f}%)")

print()
print("=" * 66)
print("B) HITOGRAMA DE HORAS (label = BRT real) - dia cheio 30/10")
print("=" * 66)
d = json.load(open(r"E:\apps\01 - TRADER\BIT_M1_1000.json", encoding="utf-8"))
h = collections.Counter()
for x in d["candles"]:
    t = lbl(x["timestamp"])
    if t.date().isoformat() == "2026-10-30":
        h[t.hour] += 1
print("  BIT 30/10:", dict(sorted(h.items())))

print()
print("=" * 66)
print("C) RESUMO DA CORRECAO DE FUSO")
print("=" * 66)
last = d["candles"][-1]["timestamp"]
print(f"  meta.fetched_at (relogio real): 10:54  (BRT)")
print(f"  ultima vela, label (epoch->UTC): {lbl(last):%H:%M}")
print(f"  ultima vela, conversao ingenua : {naive(last):%H:%M}  <- 3h atras")
print("  => epoch guarda a HORA DE BRASILIA como se fosse UTC.")
print("  => hora real BRT = ler o epoch como UTC (nao converter p/ -3).")
