"""Diagnóstico: status por bucket (turbo=Blitz, binary=Digital) para os 12 OTC do dropdown."""
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

    from iqoptionapi.stable_api import IQ_Option

    def _run():
        api = IQ_Option(creds["email"], creds["password"])
        ok = api.connect()
        print(f"connect={ok} check={api.check_connect()}")
        if not ok:
            return None
        t0 = time.time()
        data = api.get_all_init_v2(0.2)
        print(f"init_v2 elapsed={time.time()-t0:.2f}s")
        try:
            api.logout()
        except Exception:
            pass
        return data

    data = await asyncio.to_thread(_run)
    if not isinstance(data, dict):
        print("FAIL: init_v2 not dict/None")
        return

    print("top keys:", list(data.keys()))
    buckets = {}
    for option in ("turbo", "binary", "blitz"):
        block = data.get(option) or {}
        actives = block.get("actives") or {}
        buckets[option] = {}
        for _aid, active in actives.items():
            name = str(active.get("name", "")).split(".")[-1]
            buckets[option][name] = (
                bool(active.get("enabled")),
                bool(active.get("is_suspended")),
            )

    print(f"\n{'symbol':<14} | {'turbo':<22} | {'binary(Digital)':<22} | {'blitz':<22} | merged")
    print("-" * 108)
    for s in SYMBOLS:
        def fmt(b):
            if s not in buckets[b]:
                return "AUSENTE"
            en, sus = buckets[b][s]
            return f"en={'S' if en else 'N'} sus={'S' if sus else 'N'} {'OPEN' if (en and not sus) else 'CLOSED'}"
        t, bn, bl = fmt("turbo"), fmt("binary"), fmt("blitz")
        merged = "open" if any("OPEN" in x for x in (t, bn, bl)) else "closed"
        print(f"{s:<14} | {t:<22} | {bn:<22} | {bl:<22} | {merged}")

    # Turbos ausentes do bucket?
    only_turbo = sorted(set(buckets["turbo"]) - set(buckets["binary"]) - set(buckets["blitz"]))
    only_binary = sorted(set(buckets["binary"]) - set(buckets["turbo"]) - set(buckets["blitz"]))
    only_blitz = sorted(set(buckets["blitz"]) - set(buckets["turbo"]) - set(buckets["binary"]))
    print(f"\nturbo={len(buckets['turbo'])} binary={len(buckets['binary'])} blitz={len(buckets['blitz'])}")
    print(f"só em turbo={len(only_turbo)} ex={only_turbo[:10]}")
    print(f"só em binary={len(only_binary)} ex={only_binary[:10]}")
    print(f"só em blitz={len(only_blitz)} ex={only_blitz[:15]}")
    blitz_otc = sorted(s for s in buckets["blitz"] if "OTC" in s.upper())
    print(f"blitz OTC ({len(blitz_otc)}): {blitz_otc}")


if __name__ == "__main__":
    asyncio.run(main())
