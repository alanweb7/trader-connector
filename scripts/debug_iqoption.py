"""Debug script para investigar estado da conexao IQ Option"""
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
        print()

        print("=== INTERNAL STATE ===")
        print("_connected:", adapter._connected)
        print("_authenticated:", adapter._authenticated)
        print("_account_type:", adapter._account_type)
        print("_api is None:", adapter._api is None)

        if adapter._api:
            api = adapter._api
            print()
            print("=== API OBJECT ===")
            print("type:", type(api))
            print("has api attr:", hasattr(api, 'api'))
            if hasattr(api, 'api'):
                print("api.api type:", type(api.api))
                print("api.api.__dict__ keys:", list(api.api.__dict__.keys())[:20])

                print()
                print("=== CONNECTION STATE ===")
                print("check_connect():", api.check_connect())

                print()
                print("=== BALANCE SOURCES ===")
                print("api.balances_raw:", api.balances_raw)

                print()
                print("=== PROFILE ===")
                try:
                    profile = api.profile
                    print("profile:", profile)
                except Exception as e:
                    print("profile error:", e)

                print()
                print("=== API METHODS (first 30) ===")
                methods = [m for m in dir(api) if not m.startswith('_')]
                for m in methods[:30]:
                    print(f"  {m}")

                if hasattr(api, 'api'):
                    print()
                    print("=== API.API METHODS (first 30) ===")
                    api_methods = [m for m in dir(api.api) if not m.startswith('_')]
                    for m in api_methods[:30]:
                        print(f"  {m}")

                print()
                print("=== get_all_open_time (sem args) ===")
                try:
                    aos = api.get_all_open_time()
                    print("type:", type(aos))
                    if isinstance(aos, dict):
                        print("keys:", list(aos.keys())[:10])
                        if 'turbo' in aos:
                            print("turbo keys (first 10):", list(aos['turbo'].keys())[:10])
                            for k, v in list(aos['turbo'].items())[:3]:
                                print(f"  {k}: {v}")
                except Exception as e:
                    print("error:", e)

                print()
                print("=== get_candles test (EURUSD) ===")
                try:
                    c = api.get_candles("EURUSD", 60, 5, api.get_server_timestamp())
                    print("candles count:", len(c) if c else 0)
                    if c:
                        print("first:", c[0])
                except Exception as e:
                    print("error:", e)

        print()
        print("=== STATUS ===")
        status = await adapter.get_status()
        print(status)

        print()
        print("=== ACCOUNT ===")
        account = await adapter.get_account()
        print(account)

        print()
        print("=== BALANCE ===")
        balance = await adapter.get_balance()
        print(balance)

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
