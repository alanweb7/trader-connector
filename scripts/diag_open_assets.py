"""Diagnóstico: listar ativos abertos (binary/turbo) via credenciais do Supabase."""
import asyncio
import os
import sys
import time

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
from src.infrastructure.database.connection_repository import connection_repository

CONN = "27bd4e92-32e4-4bbf-9ba3-b7a651714ba5"


async def main() -> None:
    creds = connection_repository.get_with_credentials(CONN)
    if not creds or not creds.get("email") or not creds.get("password"):
        print("FAIL: no decrypted credentials")
        return
    print(f"email={creds['email']} account_type={creds.get('account_type')}")

    from iqoptionapi.stable_api import IQ_Option

    def _run():
        api = IQ_Option(creds["email"], creds["password"])
        ok = api.connect()
        print(f"connect={ok} check={api.check_connect()}")
        if not ok:
            return None
        print(f"balance={api.get_balance()}")
        t0 = time.time()
        data = api.get_all_init_v2(0.2)
        print(f"init_v2 elapsed={time.time()-t0:.2f}s type={type(data)}")
        try:
            api.logout()
        except Exception:
            pass
        return data

    data = await asyncio.to_thread(_run)
    if not isinstance(data, dict):
        print("FAIL: init_v2 not dict/None")
        return

    print("top keys:", list(data.keys())[:30])
    for option in ("binary", "turbo"):
        block = data.get(option) or {}
        actives = block.get("actives") or {}
        print(f"\n=== {option} actives={len(actives)} ===")
        open_names = []
        otc_names = []
        for aid, active in actives.items():
            name = str(active.get("name", "")).split(".")[-1]
            enabled = bool(active.get("enabled"))
            suspended = bool(active.get("is_suspended"))
            is_open = enabled and not suspended
            if "OTC" in name.upper():
                otc_names.append((name, aid, enabled, suspended, is_open))
            if is_open:
                open_names.append((name, aid))
        print(f"open_count={len(open_names)}")
        print("open sample:", open_names[:30])
        print(f"otc_count={len(otc_names)}")
        for row in sorted(otc_names):
            print("OTC", row)

    # Compare with constants
    import iqoptionapi.constants as c
    print("\nCONSTANTS OTC:", sorted(k for k in c.ACTIVES if k.endswith("-OTC")))


if __name__ == "__main__":
    asyncio.run(main())
