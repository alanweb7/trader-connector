"""
Teste minimo de conexao com a Polarium Broker (white-label Quadcode).

Fluxo exigido no prompt:
  1. conectar via WebSocket (wss://ws.polariumbroker.com/echo/websocket)
  2. autenticar com SSID: {"name": "authenticate", "msg": {"ssid": ..., "protocol": 3}}
  3. buscar candles: get_candles("EURUSD", 60, 5, time.time())

Uso:
    set POLARIUM_SSID=seu-ssid
    python scripts/test_polarium_connection.py

Login por email/senha (HTTP extrai o SSID automaticamente):
    set POLARIUM_EMAIL=user@broker.com
    set POLARIUM_PASSWORD=secret
    python scripts/test_polarium_connection.py

Opcoes:
    python scripts/test_polarium_connection.py --ssid XXX --active EURJPY --count 10
    python scripts/test_polarium_connection.py --host ws.outro-host.com   # override
"""
import argparse
import os
import sys
import threading
import time
from typing import Any, Callable, Optional

# Adicionar diretorio raiz ao path para importacoes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

CONNECT_TIMEOUT_SEC = 45
CANDLES_TIMEOUT_SEC = 20


def run_with_timeout(fn: Callable[..., Any], timeout: float, *args: Any, **kwargs: Any) -> Any:
    """
    Executa fn em thread daemon com timeout.

    Necessario porque a iqoptionapi tem busy-waits internos (get_candles,
    start_websocket) que podem girar para sempre se o servidor nao responde.
    Thread daemon: nao segura a saida do interpretador no timeout.
    """
    result: dict = {}
    done = threading.Event()

    def _target() -> None:
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - repassado ao caller
            result["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    if not done.wait(timeout):
        raise TimeoutError(
            f"{getattr(fn, '__name__', 'fn')} nao respondeu em {timeout:.0f}s"
        )
    if "error" in result:
        raise result["error"]
    return result.get("value")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teste de conexao Polarium Broker (white-label Quadcode)"
    )
    parser.add_argument("--ssid", default=os.environ.get("POLARIUM_SSID"))
    parser.add_argument("--email", default=os.environ.get("POLARIUM_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("POLARIUM_PASSWORD"))
    parser.add_argument("--active", default="EURUSD", help="Ativo (default: EURUSD)")
    parser.add_argument("--interval", type=int, default=60, help="Timeframe em segundos")
    parser.add_argument("--count", type=int, default=5, help="Quantidade de candles")
    parser.add_argument(
        "--host",
        default=os.environ.get("POLARIUM_WS_HOST"),
        help="Override do ws_host (default do perfil: ws.polariumbroker.com)",
    )
    args = parser.parse_args()

    from src.adapters.iqoption.quadcode_compat import create_iq_option, get_profile

    profile = get_profile("polarium")
    auth_mode = "SSID" if args.ssid else "email/senha"

    print("=" * 60)
    print("TESTE DE CONEXAO — POLARIUM BROKER (white-label Quadcode)")
    print("=" * 60)
    print(f"WS host:      {args.host or profile.ws_host}")
    print(f"Auth base:    {profile.auth_base}")
    print(f"Origin:       {profile.origin}")
    print(f"Autenticacao: {auth_mode}")
    print()

    if not args.ssid and not (args.email and args.password):
        print("ERRO: informe --ssid (ou POLARIUM_SSID) OU POLARIUM_EMAIL+POLARIUM_PASSWORD")
        return 2

    api = create_iq_option(
        email=args.email,
        password=args.password,
        ssid=args.ssid,
        broker_profile="polarium",
        host=args.host,
        auto_logout=False,
    )

    try:
        # 1. Conectar: WebSocket + handshake authenticate {"ssid", "protocol": 3}
        print(f"1. Conectando (timeout {CONNECT_TIMEOUT_SEC}s)...")
        ok, reason = run_with_timeout(api.connect, CONNECT_TIMEOUT_SEC)
        if not ok:
            print(f"   FALHOU: {reason}")
            return 1
        print("   OK — WebSocket conectado e autenticado")
        print()

        # 2. Sessao ativa
        print("2. Verificando sessao (get_ssid)...")
        active_ssid: Optional[str] = api.get_ssid()
        print(f"   SSID ativo: {active_ssid[:16] + '...' if active_ssid else '(nenhum)'}")
        print()

        # 3. Candles — pedido explicito do prompt
        print(
            f"3. get_candles({args.active!r}, {args.interval}, {args.count}, time.time())..."
        )
        candles = run_with_timeout(
            api.get_candles,
            CANDLES_TIMEOUT_SEC,
            args.active,
            args.interval,
            args.count,
            time.time(),
        )
        print(f"   Recebidos: {len(candles)} candles")
        for candle in candles:
            print(f"   {candle}")
        print()

        if not candles:
            print("FALHA: conexao ok, mas nenhuma candle recebida")
            return 1

        print("=" * 60)
        print("TESTE OK — Polarium autenticou e retornou candles")
        print("=" * 60)
        return 0

    except TimeoutError as exc:
        print(f"FALHA: timeout — {exc}")
        return 1
    except Exception as exc:
        print(f"FALHA: {exc!r}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        try:
            api.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
