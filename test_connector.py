import urllib.request
for url in ["http://localhost:8000/connections", "http://127.0.0.1:8000/connections"]:
    try:
        r = urllib.request.urlopen(url, timeout=5)
        print(f"{url} => STATUS {r.status}")
        print(r.read().decode()[:200])
    except Exception as e:
        print(f"{url} => ERRO: {type(e).__name__}: {e}")
