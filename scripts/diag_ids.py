"""Diagnóstico: active_id estático (constants.ACTIVES) vs ids reais nos buckets turbo/binary/blitz."""
import asyncio
import sys
import time

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
from src.infrastructure.database.connection_repository import connection_repository

CONN = "27bd4e92-32e4-4bbf-9ba3-b7a651714ba5"
SYMBOLS = [
    "EURUSD-OTC", "EURGBP-OTC", "USDJPY-OTC", "GBPUSD-OTC",
    "EURJPY-OTC", "AUDCAD-OTC", "GBPJPY-OTC", "NZDUSD-OTC",
    "USDCHF-OTC", "USDHKD-OTC", "USDINR-OTC", "USDSGD-OTC",
]


async def main() -> None:
    creds = connection_repository.get_with_credentials(CONN)
    if not creds or not creds.get("email") or not creds.get("password"):
        print("FAIL: no decrypted credentials")
        return

    import iqoptionapi.constants as _OP
    from iqoptionapi.stable_api import IQ_Option

    def _run():
        api = IQ_Option(creds["email"], creds["password"])
        ok = api.connect()
        if not ok:
            return None
        data = api.get_all_init_v2(0.2)
        try:
            api.logout()
        except Exception:
            pass
        return data

    data = await asyncio.to_thread(_run)
    if not isinstance(data, dict):
        print("FAIL: init_v2")
        return

    buckets = {}
    for option in ("turbo", "binary", "blitz"):
        actives = (data.get(option) or {}).get("actives") or {}
        buckets[option] = {}
        for aid, active in actives.items():
            name = str(active.get("name", "")).split(".")[-1]
            buckets[option][name] = (
                str(aid),
                bool(active.get("enabled")),
                bool(active.get("is_suspended")),
            )

    print(f"{'symbol':<14} | {'constants':<10} | {'turbo id':<10} | {'binary id':<10} | {'blitz id':<10}")
    print("-" * 70)
    for s in SYMBOLS:
        cid = str(_OP.ACTIVES.get(s, "AUSENTE"))
        ids = []
        for b in ("turbo", "binary", "blitz"):
            ids.append(buckets[b].get(s, ("AUSENTE",))[0])
        print(f"{s:<14} | {cid:<10} | {ids[0]:<10} | {ids[1]:<10} | {ids[2]:<10}")

    print("\nconstants tem -OTC:", sorted(k for k in _OP.ACTIVES if k.endswith("-OTC")))


if __name__ == "__main__":
    asyncio.run(main())
