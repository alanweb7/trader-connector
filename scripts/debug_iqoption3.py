"""Acesso direto e breve a iqoptionapi para observar assinaturas reais e um teste de ordem real em pratica."""
import sys
import os
import time
import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EMAIL = "99tisistemas@gmail.com"
PASSWORD = "@seguro#LIVE332"

from iqoptionapi.stable_api import IQ_Option


def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[{now_iso()}] {msg}")


def run():
    log("criando API object")
    api = IQ_Option(EMAIL, PASSWORD)

    log("conectando (sync, timeout interno via disconnect depois)")
    try:
        api.connect()
    except Exception as e:
        log(f"api.connect() levantou: {type(e).__name__}: {e}")

    time.sleep(3)

    log(f"check_connect = {api.check_connect()}")

    log("--- get_all_open_time: varias assinaturas ---")
    for args in [(), (True,), (False,)]:
        try:
            r = api.get_all_open_time(*args)
            t = type(r).__name__
            preview = ""
            if isinstance(r, dict):
                preview = f"keys={list(r.keys())[:12]}"
                if "turbo" in r and isinstance(r["turbo"], dict):
                    syms = list(r["turbo"].keys())[:8]
                    preview += f" | turbo={len(r['turbo'])} exemplars: {syms}"
            elif isinstance(r, list):
                preview = f"len={len(r)} first={r[0] if r else None}"
            log(f"get_all_open_time{args} -> {t} | {preview}")
        except TypeError as e:
            log(f"get_all_open_time{args} -> TypeError: {e}")
        except Exception as e:
            log(f"get_all_open_time{args} -> {type(e).__name__}: {e}")

    log("--- get_candles: varias assinaturas ---")
    # Checar assinatura
    try:
        import inspect
        log(f"get_candles signature: {inspect.signature(api.get_candles)}")
    except Exception as e:
        log(f"não conseguiu ler assinatura: {e}")

    for args in [
        ("EURUSD",),
        ("EURUSD", 60),
        ("EURUSD", 60, 10),
        ("EURUSD", 60, 10, int(time.time())),
    ]:
        try:
            r = api.get_candles(*args)
            t = type(r).__name__
            preview = ""
            if isinstance(r, list):
                preview = f"len={len(r)}"
                if r:
                    preview += f" first={r[0]}"
            log(f"get_candles{args} -> {t} | {preview}")
        except TypeError as e:
            log(f"get_candles{args} -> TypeError: {e}")
        except Exception as e:
            log(f"get_candles{args} -> {type(e).__name__}: {e}")

    log("--- get_balance ---")
    try:
        import inspect
        log(f"get_balance signature: {inspect.signature(api.get_balance)}")
    except Exception as e:
        log(f"não conseguiu ler assinatura: {e}")
    for args in [(), ("practice",), ("real",)]:
        try:
            r = api.get_balance(*args)
            log(f"get_balance{args} -> {r!r}")
        except TypeError as e:
            log(f"get_balance{args} -> TypeError: {e}")
        except Exception as e:
            log(f"get_balance{args} -> {type(e).__name__}: {e}")

    log("--- profile ---")
    try:
        log(f"profile = {api.profile!r}")
    except Exception as e:
        log(f"profile -> {type(e).__name__}: {e}")

    log("--- buy dry-run (signatura somente se possível) ---")
    try:
        import inspect
        sig = inspect.signature(api.buy)
        log(f"buy signature: {sig}")
    except Exception as e:
        log(f"não conseguiu ler assinatura: {e}")

    log("--- buy REAL (pratica, eurousd, 1 unidade, 1 min) ---")
    try:
        # Tentar com assinatura comum: buy(amount, asset, direction, time)
        # direction: 1=CALL, 0=PUT
        log("tentando buy(1, 'EURUSD', 1, 1) ...")
        t0 = time.time()
        resultado = api.buy(1, "EURUSD", 1, 1)
        dt = time.time() - t0
        log(f"buy(1,'EURUSD',1,1) retornou em {dt:.2f}s: {resultado!r}")
    except TypeError as e:
        log(f"buy(1,'EURUSD',1,1) TypeError: {e}")
    except Exception as e:
        log(f"buy(1,'EURUSD',1,1) -> {type(e).__name__}: {e}")

    time.sleep(1)

    log("--- tentando obter resultado da ordem (se ID disponível) ---")
    try:
        # A biblioteca pode ter get_order ou api.result
        for attr in ["get_order", "result", "get_trade_results", "trades"]:
            if hasattr(api, attr):
                log(f"api.{attr} existe: {getattr(api, attr)!r}")
    except Exception as e:
        log(f"erro ao inspecionar: {e}")

    log("disconnecting")
    try:
        api.disconnect()
    except Exception as e:
        log(f"disconnect levantou: {e}")
    log("fim")


if __name__ == "__main__":
    run()
