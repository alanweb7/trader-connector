"""Debug script para investigar estado da conexao IQ Option — v2"""
import asyncio
import sys
import os

if not os.environ.get("IQOPTION_EMAIL") or not os.environ.get("IQOPTION_PASSWORD"):
    raise SystemExit(
        "Defina IQOPTION_EMAIL e IQOPTION_PASSWORD no ambiente antes de executar."
    )

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.adapters.iqoption import IQOptionAdapter
from src.core.errors import BrokerError


async def debug():
    email = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
    password = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
    account_type = "practice"

    adapter = IQOptionAdapter()
    try:
        result = await adapter.connect({
            "email": email,
            "password": password,
            "account_type": account_type,
        })
        print("=== CONNECT RESULT ===")
        print(result)

        api = adapter._api
        print("\n=== API.PYTHON API OBJECT ===")
        iqapi = api.api
        print("type:", type(iqapi))
        print("dir (public):", [m for m in dir(iqapi) if not m.startswith('_')])

        print("\n=== check_connect ===")
        print("result:", api.check_connect())

        print("\n=== get_all_open_time: tentando assinaturas ===")
        for args in [(), (True,), (False,), (1,)]:
            try:
                r = api.get_all_open_time(*args)
                print(f"  get_all_open_time{args} -> type={type(r).__name__}")
                if isinstance(r, dict):
                    print(f"    keys={list(r.keys())}")
                    if 'turbo' in r:
                        print(f"    turbo symbols (first 5): {list(r['turbo'].keys())[:5]}")
                        for k, v in list(r['turbo'].items())[:2]:
                            print(f"      {k}: {v}")
                elif isinstance(r, list):
                    print(f"    len={len(r)}, first={r[0] if r else None}")
                else:
                    print(f"    repr={repr(r)[:200]}")
            except TypeError as e:
                print(f"  get_all_open_time{args} -> TypeError: {e}")
            except Exception as e:
                print(f"  get_all_open_time{args} -> {type(e).__name__}: {e}")

        print("\n=== get_candles assinatura ===")
        for args in [("EURUSD",), ("EURUSD", 60), ("EURUSD", 60, 5), ("EURUSD", 60, 5, 0)]:
            try:
                r = api.get_candles(*args)
                print(f"  get_candles{args} -> type={type(r).__name__}, len={len(r) if hasattr(r,'__len__') else 'n/a'}")
                if isinstance(r, list) and r:
                    print(f"    first={r[0]}")
            except TypeError as e:
                print(f"  get_candles{args} -> TypeError: {e}")
            except Exception as e:
                print(f"  get_candles{args} -> {type(e).__name__}: {e}")

        print("\n=== get_balance ===")
        for args in [(), ("practice",), ("real",)]:
            try:
                r = api.get_balance(*args)
                print(f"  get_balance{args} -> {r}")
            except TypeError as e:
                print(f"  get_balance{args} -> TypeError: {e}")
            except Exception as e:
                print(f"  get_balance{args} -> {type(e).__name__}: {e}")

        print("\n=== profile ===")
        try:
            print("profile:", api.profile)
        except Exception as e:
            print(f"error: {e}")

        print("\n=== server_timestamp ===")
        try:
            print("timestamp:", api.get_server_timestamp())
        except Exception as e:
            print(f"error: {e}")

        print("\n=== buy (dry-run signature test) ===")
        for args in [(10, "EURUSD", 1, 1), (10, "EURUSD", 1, 1, "practice")]:
            try:
                # Não executa realmente — só testa assinatura
                import inspect
                sig = inspect.signature(api.buy)
                print(f"  buy signature: {sig}")
                break
            except Exception as e:
                print(f"  error: {e}")

    except BrokerError as e:
        print("BROKER ERROR:", e.message, e.code)
        if e.original_error:
            print("original:", e.original_error)
    except Exception as e:
        print("ERROR:", e)
        import traceback
        traceback.print_exc()
    finally:
        if adapter._connected:
            await adapter.disconnect()
            print("\nDisconnected")


if __name__ == "__main__":
    asyncio.run(debug())
