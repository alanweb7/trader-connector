"""
Patch idempotente da iqoptionapi: substitui os busy-waits `while ...: pass`
(sem sleep) por loops com time.sleep + timeout.

Motivo: toda tentativa de login que perde a resposta do servidor (WS fechado,
retry abandonado por timeout) ficava girando em 100% de CPU para sempre,
roubando o GIL e atrasando o event loop do servidor (uvicorn).

Uso:
    python scripts/patch_iqoptionapi.py          # aplica
    python scripts/patch_iqoptionapi.py --check  # só verifica (exit 1 se falta)

Aplicar de novo apos recriar o venv.
"""
import pathlib
import py_compile
import sys

PKG = (
    pathlib.Path(__file__).resolve().parents[1]
    / "venv"
    / "Lib"
    / "site-packages"
    / "iqoptionapi"
)
MARK = "# [patched-broker] sleep+timeout"

PATCHES = [
    {
        "file": "api.py",
        "old": (
            "        self.authenticated=None\n"
            "        self.ssid(global_value.SSID[self.object_id],req_id)  # pylint: disable=no"
            "t-callable\n"
            "        while self.authenticated==None:\n"
            "            pass\n"
        ),
        "new": (
            "        self.authenticated=None\n"
            "        self.ssid(global_value.SSID[self.object_id],req_id)  # pylint: disable=no"
            "t-callable\n"
            f"        _auth_wait = 0  {MARK}\n"
            "        while self.authenticated==None:\n"
            "            time.sleep(0.01)\n"
            "            _auth_wait += 1\n"
            "            if _auth_wait > 600:  # 6s: servidor nao respondeu\n"
            "                self.authenticated = False\n"
            "                break\n"
        ),
    },
    {
        "file": "api.py",
        "old": (
            "        while self.profile.msg==None:\n"
            "            pass\n"
        ),
        "new": (
            f"        _profile_wait = 0  {MARK}\n"
            "        while self.profile.msg==None:\n"
            "            time.sleep(0.01)\n"
            "            _profile_wait += 1\n"
            "            if _profile_wait > 600:  # 6s: servidor nao respondeu\n"
            "                self.profile.msg = False\n"
            "                break\n"
        ),
    },
    {
        "file": "api.py",
        "old": (
            "        self.timesync.server_timestamp = None\n"
            "        while True:\n"
            "            try:\n"
            "                if self.timesync.server_timestamp != None:\n"
            "                    break\n"
            "            except:\n"
            "                pass\n"
            "        return True,None\n"
        ),
        "new": (
            "        self.timesync.server_timestamp = None\n"
            f"        _timesync_wait = 0  {MARK}\n"
            "        while True:\n"
            "            try:\n"
            "                if self.timesync.server_timestamp != None:\n"
            "                    break\n"
            "            except:\n"
            "                pass\n"
            "            time.sleep(0.01)\n"
            "            _timesync_wait += 1\n"
            "            if _timesync_wait > 1000:  # 10s: sem timesync\n"
            "                return False, 'timesync timeout'\n"
            "        return True,None\n"
        ),
    },
    {
        "file": "stable_api.py",
        "old": (
            "            while global_value.balance_id[self.api.object_id]==None:\n"
            "                pass\n"
        ),
        "new": (
            f"            _bal_wait = 0  {MARK}\n"
            "            while global_value.balance_id[self.api.object_id]==None:\n"
            "                time.sleep(0.01)\n"
            "                _bal_wait += 1\n"
            "                if _bal_wait > 600:  # 6s: sem balance_id\n"
            "                    break\n"
        ),
    },
]


def main() -> int:
    check_only = "--check" in sys.argv
    if not PKG.is_dir():
        print(f"ERRO: pacote nao encontrado em {PKG}")
        return 2
    failures = 0
    for i, patch in enumerate(PATCHES, 1):
        path = PKG / patch["file"]
        src = path.read_text(encoding="utf-8")
        if MARK in src and patch["old"] not in src:
            print(f"[{i}] {patch['file']}: ja aplicado")
            continue
        if patch["old"] not in src:
            print(f"[{i}] {patch['file']}: PADRAO NAO ENCONTRADO (lib mudou?)")
            failures += 1
            continue
        if check_only:
            print(f"[{i}] {patch['file']}: FALTA APLICAR")
            failures += 1
            continue
        path.write_text(src.replace(patch["old"], patch["new"], 1), encoding="utf-8")
        print(f"[{i}] {patch['file']}: aplicado")
    if failures:
        return 1
    if not check_only:
        for name in ("api.py", "stable_api.py"):
            py_compile.compile(str(PKG / name), doraise=True)
        print("OK: patches aplicados e compilados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
