"""Teste separado B3: busca apenas as ULTIMAS velas (não as 1000),
atualiza dataset local com idempotencia e complementa a ultima vela se nao fechada."""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
CONN = "e793ef85-ff1f-448d-bd4b-a029dc1f85ff"

ASSETS = {"BIT": r"E:\apps\01 - TRADER\BIT_M1_1000.json",
          "WIN": r"E:\apps\01 - TRADER\WIN_M1_1000.json"}

def get_latest(asset, count=5):
    """Busca apenas as ultimas `count` velas do CONNECTOR."""
    url = f"http://127.0.0.1:8000/connections/{CONN}/candles?asset={asset}&timeframe=1&count={count}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode()).get("candles", [])

def is_closed(candle, now=None):
    """Uma vela e considerada fechada quando o proximo timestamp ja passou."""
    now = now or datetime.now(timezone.utc)
    ts = candle["timestamp"]
    # epoch armazena hora de Brasilia como se fosse UTC
    candle_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    # proxima vela = candle_dt + 1 minuto
    next_dt = candle_dt + timedelta(minutes=1)
    return next_dt <= now

def update_dataset(asset, path):
    # 1) carrega dataset existente
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        existing = data.get("candles", [])
    except Exception:
        existing = []

    # 2) busca apenas as ultimas 5 velas (idempotencia: nao busca as 1000)
    latest = get_latest(asset, count=5)
    if not latest:
        print(f"{asset}: ERRO ao buscar ultimas velas")
        return

    # 3) mescla: remove duplicatas por timestamp e mantem ordem crescente
    merged = {c["timestamp"]: c for c in existing}
    for c in latest:
        merged[c["timestamp"]] = c
    merged_list = sorted(merged.values(), key=lambda x: x["timestamp"])

    # 4) complementa a ultima vela se nao foi fechada
    now = datetime.now(timezone.utc)
    last_candle = merged_list[-1] if merged_list else None
    if last_candle and not is_closed(last_candle, now):
        # a ultima vela ainda esta em aberto — mantemos como aberta (não fechamos artificialmente)
        # mas marcamos no meta
        print(f"{asset}: ultima vela {last_candle['timestamp']} ainda em aberto (nao fechada)")

    # 5) salva
    meta = {
        "asset": asset,
        "symbol": f"{asset}$",
        "contract": "WINZ26" if asset == "WIN" else "BITX26",
        "market": "B3 (MetaTrader 5)",
        "broker": "mt5",
        "connection_id": CONN,
        "timeframe": "1m",
        "count": len(merged_list),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "source": "http://127.0.0.1:8000 -> http://127.0.0.1:8001",
        "last_candle_open": last_candle and not is_closed(last_candle, now),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "candles": merged_list}, f, ensure_ascii=False, indent=2)

    print(f"{asset}: dataset atualizado -> {len(merged_list)} velas (adicionadas {len(latest)} novas)")

if __name__ == "__main__":
    for asset, path in ASSETS.items():
        update_dataset(asset, path)