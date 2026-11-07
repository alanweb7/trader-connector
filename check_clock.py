"""Confere o relogio da maquina contra o header Date de fontes externas."""
import urllib.request
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

urls = [
    "https://www.google.com/",
    "https://github.com/",
    "https://www.cloudflare.com/",
    "https://httpbin.org/get",
]
ok = []
for u in urls:
    try:
        req = urllib.request.Request(u, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            dh = r.headers.get("Date")
        if dh:
            ext = datetime(*__import__("email").utils.parsedate(dh)[:6],
                           tzinfo=timezone.utc)
            ok.append((u, ext))
            print(f"  {u:35} Date: {ext:%d/%m/%Y %H:%M:%S} UTC")
    except Exception as e:
        print(f"  {u:35} falhou: {type(e).__name__} {e}")

mach = datetime.now(timezone.utc)
print(f"\n  maquina UTC : {mach:%d/%m/%Y %H:%M:%S}")
print(f"  maquina BRT : {datetime.now(BRT):%d/%m/%Y %H:%M:%S}")
for u, ext in ok:
    d = (mach - ext).total_seconds()
    print(f"  delta vs {u.split('/')[2]:15}: {d:+.0f} s")
