"""
Smoke do endpoint WS de candles (/ws/connections/{id}).

Conecta, assina um ativo e espera candles (mode "live" via canal
candle-generated, ou "poll" via fallback REST). Imprime o payload cru
da primeira vela para conferir o mapeamento de campos.

Execute (servidor local em :8000):
    python scripts/test_ws_candles.py
    python scripts/test_ws_candles.py --asset EURUSD-OTC --timeframe 1 --expect 3
    python scripts/test_ws_candles.py --connection-id <id>

Exit codes: 0 = recebeu ao menos 1 candle; 1 = falhou; 2 = servidor fora.
"""
import argparse
import asyncio
import json
import os
import sys
import time

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL = os.environ.get("BROKER_BASE_URL", "http://localhost:8000")


def resolve_connection_id() -> str:
    """Pega a primeira connection connected/ready via GET /connections."""
    r = httpx.get(f"{BASE_URL}/connections", timeout=10)
    r.raise_for_status()
    conns = r.json().get("connections", [])
    for conn in conns:
        if str(conn.get("status", "")).lower() in ("connected", "ready"):
            return conn["id"]
    if conns:
        return conns[0]["id"]
    raise SystemExit("Nenhuma conexao encontrada em GET /connections")


async def run(args: argparse.Namespace) -> int:
    connection_id = args.connection_id or resolve_connection_id()
    ws_base = BASE_URL.replace("http://", "ws://", 1).replace(
        "https://", "wss://", 1
    )
    url = f"{ws_base}/ws/connections/{connection_id}"
    print(f"Conectando: {url}")

    got: list = []
    modes: set = set()
    async with websockets.connect(url, open_timeout=15) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 15))
        print(f"<- {json.dumps(first)}")
        if first.get("type") != "ready":
            print("FAIL: esperava mensagem 'ready'")
            return 1

        await ws.send(
            json.dumps(
                {
                    "action": "subscribe",
                    "asset": args.asset,
                    "timeframe": args.timeframe,
                }
            )
        )
        print(f"-> subscribe {args.asset} M{args.timeframe}")

        deadline = time.time() + args.timeout
        first_raw_done = False
        while time.time() < deadline and len(got) < args.expect:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.5, deadline - time.time())
                )
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "candle":
                got.append(msg)
                candle = msg.get("candle", {})
                if not first_raw_done:
                    first_raw_done = True
                    print(
                        f"<- candle[mode={msg.get('mode')}] payload cru: "
                        f"{json.dumps(candle)}"
                    )
                else:
                    print(
                        f"<- candle[mode={msg.get('mode')}] "
                        f"ts={candle.get('timestamp')} "
                        f"O={candle.get('open')} H={candle.get('high')} "
                        f"L={candle.get('low')} C={candle.get('close')}"
                    )
            elif mtype in ("subscribed", "status", "unsubscribed", "pong", "error"):
                print(f"<- {json.dumps(msg)}")
                if mtype in ("subscribed", "status") and msg.get("mode"):
                    modes.add(msg["mode"])
                if mtype == "error" and not msg.get("asset"):
                    print("FAIL: erro fatal do endpoint")
                    return 1

        try:
            await ws.send(
                json.dumps(
                    {
                        "action": "unsubscribe",
                        "asset": args.asset,
                        "timeframe": args.timeframe,
                    }
                )
            )
            await asyncio.wait_for(ws.recv(), 5)
        except Exception:  # noqa: BLE001
            pass

    print(
        f"\nResumo: {len(got)}/{args.expect} candles recebidos, "
        f"modos observados: {sorted(modes) or ['(nenhum)']}"
    )
    if got:
        print("OK: endpoint WS entregou candles")
        return 0
    print("FAIL: nenhum candle recebido no prazo")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke do WS de candles")
    parser.add_argument("--connection-id", default=None)
    parser.add_argument("--asset", default="EURUSD-OTC")
    parser.add_argument("--timeframe", type=int, default=1)
    parser.add_argument("--expect", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (ConnectionRefusedError, OSError) as exc:
        print(f"Servidor nao respondeu em {BASE_URL}: {exc}")
        return 2
    except httpx.HTTPError as exc:
        print(f"Erro ao resolver connection: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
