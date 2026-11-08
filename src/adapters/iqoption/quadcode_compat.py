"""
Camada de compatibilidade Quadcode: parametriza hosts hardcoded da lib iqoptionapi.

A iqoptionapi (fork victalejo) embute o host da IQ Option em 6 pontos fixos:

  - stable_api.py:120   IQOptionAPI("iqoption.com", ...) dentro de IQ_Option.connect()
  - http/login.py:17    https://auth.iqoption.com/api/v2/login
  - http/login.py:39    https://auth.iqoption.com/api/v2/verify/2fa
  - http/logout.py:17   https://auth.iqoption.com/api/v1.0/logout
  - ws/client.py:403    logout no auto-reconnect (WebsocketClient.on_open)
  - ws/client.py:418    login no auto-reconnect (WebsocketClient.on_open)

Corretoras white-label Quadcode (ex: Polarium Broker) usam os MESMOS canais
("authenticate" com {"ssid": ..., "protocol": 3}, buy, buy-options...) com
hosts diferentes. Este módulo aplica monkeypatches idempotentes na lib em
tempo de execução — sem editar o site-packages (sobrevive a recriar o venv).

Perfis:
    iqoption -> wss://iqoption.com/echo/websocket
                https://auth.iqoption.com/api/v{1.0,2}/...
    polarium -> wss://ws.trade.polariumbroker.com/echo/websocket
                https://auth.trade.polariumbroker.com/api/v{1.0,2}/...
                (descobertos via GET https://api.trade.polariumbroker.com/v1/endpoints)

Seleção de perfil:
    - por instância: create_iq_option(broker_profile="polarium")
    - global via env: BROKER_PROFILE=polarium
    - overrides por env: POLARIUM_WS_HOST, POLARIUM_AUTH_BASE, POLARIUM_ORIGIN

Uso direto (mesmo fluxo do prompt):
    from src.adapters.iqoption.quadcode_compat import create_iq_option
    api = create_iq_option(ssid="SEU_SSID_AQUI", broker_profile="polarium")
    ok, reason = api.connect()
"""
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

DEFAULT_PROFILE_NAME = "iqoption"

# UA de navegador: as white-labels ficam atrás de Cloudflare e bloqueiam
# UA de bot/python no handshake do WebSocket.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class QuadcodeProfile:
    """Endpoints de uma corretora sobre a plataforma Quadcode."""

    name: str
    ws_host: str  # wss://{ws_host}/echo/websocket (handshake WebSocket)
    auth_base: str  # {auth_base}/api/v2/login, /api/v2/verify/2fa, /api/v1.0/logout
    origin: str  # Origin no handshake WS e nas requisições HTTP da sessão
    user_agent: str = USER_AGENT


PROFILES: Dict[str, QuadcodeProfile] = {
    "iqoption": QuadcodeProfile(
        name="iqoption",
        ws_host="iqoption.com",
        auth_base="https://auth.iqoption.com",
        origin="https://iqoption.com",
    ),
    "polarium": QuadcodeProfile(
        # Hosts descobertos via https://api.trade.polariumbroker.com/v1/endpoints
        # (config runtime do white-label): trading_cluster_websocket = ws.trade,
        # auth_api = auth.trade (serve /api/v2/login clássico da iqoptionapi),
        # Origin = app de trading (trade.polariumbroker.com).
        name="polarium",
        ws_host="ws.trade.polariumbroker.com",
        auth_base="https://auth.trade.polariumbroker.com",
        origin="https://trade.polariumbroker.com",
    ),
}


def get_profile(name: Optional[str] = None) -> QuadcodeProfile:
    """
    Resolve o perfil ativo: argumento > env BROKER_PROFILE > default (iqoption).

    Overrides por env (ex: POLARIUM_WS_HOST=ws.outro-broker.com):
        {PERFIL}_WS_HOST, {PERFIL}_AUTH_BASE, {PERFIL}_ORIGIN
    """
    key = (name or os.environ.get("BROKER_PROFILE") or DEFAULT_PROFILE_NAME)
    key = key.strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Perfil de broker desconhecido: {key!r} "
            f"(disponiveis: {sorted(PROFILES)})"
        )
    profile = PROFILES[key]
    prefix = key.upper()
    overrides: Dict[str, str] = {}
    for field, env_name in (
        ("ws_host", f"{prefix}_WS_HOST"),
        ("auth_base", f"{prefix}_AUTH_BASE"),
        ("origin", f"{prefix}_ORIGIN"),
    ):
        value = os.environ.get(env_name)
        if value:
            overrides[field] = value
    if overrides:
        profile = replace(profile, **overrides)
    return profile


# Contexto por thread: host/perfil escolhidos na instância IQ_Option são
# repassados ao factory do IQOptionAPI dentro de IQ_Option.connect() (roda
# na MESMA thread chamadora, via asyncio.to_thread).
_ctx = threading.local()
_APPLIED = False
_APPLY_LOCK = threading.Lock()


def _auth_base_for(api) -> str:
    """Base de autenticação HTTP de um IQOptionAPI (perfil da instância)."""
    profile = getattr(api, "quadcode_profile", None)
    if profile is None:
        profile = get_profile()
    return profile.auth_base


# ---------------------------------------------------------------------------
# Anti-deadlock do ssl_Mutex da iqoptionapi
# ---------------------------------------------------------------------------
#
# A lib serializa o envio de mensagens no WebSocket com
# `global_value.ssl_Mutex[object_id]` (threading.Lock — NÃO reentrante).
# O balanço acquire/release está quebrado em três pontos de ws/client.py:
#
#   - on_message (49/372): adquire no início e só libera no fim — qualquer
#     exceção no meio (JSON inválido, ativo desconhecido) vaza o lock.
#   - on_open (424/433): libera SEM ter adquirido (RuntimeError).
#   - on_close (437): adquire e NUNCA libera — o auto-reconnect chama
#     run_forever() com o lock retido; se o DNS falhar ([Errno 11001]
#     getaddrinfo failed), o lock fica preso para sempre.
#
# Cada lock vazado consome uma thread do executor padrão do asyncio
# (min(32, cpus+4) = 12 com 8 CPUs). Com o pool saturado, TODAS as rotas do
# CONNECTOR que usam asyncio.to_thread (/health, /connections,
# /connections/{id}) expiram — foi o que zerou o /mercado no app.
#
# Correção (sem editar o site-packages — sobrevive a recriar o venv):
#   - mutex próprio: reentrante, com timeout e release sem dono = no-op;
#   - on_message: try/finally (libera sempre);
#   - on_close: sem o acquire que vazava;
#   - send_websocket_request: acquire com timeout (nunca trava para sempre).

# Segundos que um send espera pelo mutex antes de seguir sem ele
_SAFE_MUTEX_TIMEOUT = 5.0


class _SafeMutex:
    """Mutex tolerante a lock vazado (substitui o threading.Lock da lib).

    - reentrante: a mesma thread pode adquirir várias vezes (a lib adquire
      em camadas diferentes — on_message + send_websocket_request);
    - `acquire()` tem timeout: nunca bloqueia para sempre;
    - `release()` sem dono = no-op (o `on_open` da lib libera sem adquirir
      e o `on_close` segura lock de outra thread);
    - `force_release()`: zera todos os níveis da thread atual (órfãos de
      exceção).
    """

    def __init__(self, timeout: float = _SAFE_MUTEX_TIMEOUT):
        self._cond = threading.Condition()
        self._owner: Optional[int] = None
        self._count = 0
        self._timeout = timeout

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if timeout is None or timeout < 0:
            timeout = self._timeout
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:
                self._count += 1
                return True
            if not blocking:
                if self._count:
                    return False
                self._owner = me
                self._count = 1
                return True
            deadline = time.monotonic() + timeout
            while self._count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            self._owner = me
            self._count = 1
            return True

    def release(self) -> None:
        me = threading.get_ident()
        with self._cond:
            if self._owner != me:
                return  # não é dona (ou nunca foi adquirido) → no-op
            self._count -= 1
            if self._count <= 0:
                self._count = 0
                self._owner = None
                self._cond.notify_all()

    def force_release(self) -> None:
        """Libera todos os níveis adquiridos pela thread atual."""
        me = threading.get_ident()
        with self._cond:
            if self._owner != me:
                return
            self._count = 0
            self._owner = None
            self._cond.notify_all()

    def locked(self) -> bool:
        with self._cond:
            return bool(self._count)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def apply_patches() -> None:
    """Aplica os monkeypatches na iqoptionapi (idempotente)."""
    global _APPLIED
    if _APPLIED:
        return
    with _APPLY_LOCK:
        if _APPLIED:
            return

        import iqoptionapi.global_value as global_value
        import iqoptionapi.stable_api as stable_api
        import iqoptionapi.ws.client as ws_client
        from iqoptionapi.api import IQOptionAPI
        from iqoptionapi.http.login import Login, _2FA
        from iqoptionapi.http.logout import Logout

        original_iq_option_init = stable_api.IQ_Option.__init__
        original_iq_option_connect = stable_api.IQ_Option.connect
        original_wsclient_init = ws_client.WebsocketClient.__init__
        original_init_global_value = IQOptionAPI.init_global_value
        original_send_websocket_request = IQOptionAPI.send_websocket_request
        original_on_message = ws_client.WebsocketClient.on_message

        def iq_option_init(
            self,
            email,
            password,
            http_proxy_host=None,
            http_proxy_port=None,
            http_proxy_auth=None,
            set_ssid=None,
            auto_logout=True,
            host=None,
            broker_profile=None,
        ):
            """IQ_Option.__init__ + host/broker_profile para white-label."""
            original_iq_option_init(
                self,
                email,
                password,
                http_proxy_host=http_proxy_host,
                http_proxy_port=http_proxy_port,
                http_proxy_auth=http_proxy_auth,
                set_ssid=set_ssid,
                auto_logout=auto_logout,
            )
            self._quadcode_host = host
            self._quadcode_profile = get_profile(broker_profile)
            # UA de navegador (o default da lib é um Chrome/Linux antigo)
            self.SESSION_HEADER = {"User-Agent": self._quadcode_profile.user_agent}

        def iq_option_connect(self):
            """IQ_Option.connect() com contexto de perfil para o factory."""
            _ctx.ws_host = getattr(self, "_quadcode_host", None)
            _ctx.profile = getattr(self, "_quadcode_profile", None)
            try:
                return original_iq_option_connect(self)
            finally:
                _ctx.ws_host = None
                _ctx.profile = None

        def profiled_iqoptionapi(host=None, username=None, password=None, **kwargs):
            """Substitui stable_api.IQOptionAPI: host vem do perfil, não do
            "iqoption.com" hardcoded em stable_api.py:120."""
            profile = getattr(_ctx, "profile", None) or get_profile()
            ws_host = getattr(_ctx, "ws_host", None) or profile.ws_host
            api = IQOptionAPI(ws_host, username, password, **kwargs)
            api.quadcode_profile = profile
            try:
                api.session.headers.update(
                    {"User-Agent": profile.user_agent, "Origin": profile.origin}
                )
            except Exception:
                pass
            return api

        def login_post(self, data=None, headers=None):
            url = _auth_base_for(self.api) + "/api/v2/login"
            return self.api.send_http_request_v2(
                method="POST", url=url, data=data, headers=headers
            )

        def twofa_post(self, data=None):
            url = _auth_base_for(self.api) + "/api/v2/verify/2fa"
            headers = {"CONTENT-TYPE": "application/json"}
            return self.api.send_http_request_v2(
                method="POST", url=url, data=data, headers=headers
            )

        def logout_post(self, data=None, headers=None):
            url = _auth_base_for(self.api) + "/api/v1.0/logout"
            return self.api.send_http_request_v2(
                method="POST", url=url, data=data, headers=headers
            )

        def wsclient_init(self, api):
            """WebsocketClient.__init__ + headers de navegador no handshake."""
            original_wsclient_init(self, api)
            profile = getattr(api, "quadcode_profile", None) or get_profile()
            try:
                # WebSocketApp.header: lista "Name: value" lida no run_forever
                self.wss.header = [
                    f"User-Agent: {profile.user_agent}",
                    f"Origin: {profile.origin}",
                ]
                # consumido por wsclient_on_open (auto-reconnect)
                self.wss.quadcode_profile = profile
            except Exception:
                pass

        def _safe_release(wss):
            """Libera o ssl_Mutex do socket sem levantar RuntimeError.

            A lib liberava o lock SEM ter adquirido (on_open) — com o
            threading.Lock original isso é RuntimeError; com o _SafeMutex
            é no-op (a thread atual não é a dona do lock).
            """
            mutex = global_value.ssl_Mutex.get(id(wss))
            if mutex is None:
                return
            try:
                mutex.release()
            except RuntimeError:
                pass

        def wsclient_on_open(wss):
            """WebsocketClient.on_open — auto-reconnect com auth_base do perfil
            (substitui os URLs auth.iqoption.com de ws/client.py:403 e :418)."""
            logger = logging.getLogger("iqoptionapi.ws.client")
            logger.debug("Websocket client connected.")
            global_value.check_websocket_if_connect[id(wss)] = 1

            if id(wss) not in global_value.auto_reconnect:
                return
            if id(wss) not in global_value.happen_close:
                return

            if (
                global_value.auto_reconnect[id(wss)] is True
                and global_value.happen_close[id(wss)] is True
            ):
                import requests

                profile = getattr(wss, "quadcode_profile", None) or get_profile()
                headers = {"User-Agent": profile.user_agent}
                try:
                    old_session = global_value.low_level_reconnect_session[id(wss)]
                    old_session.request(
                        method="POST",
                        url=profile.auth_base + "/api/v1.0/logout",
                        headers=headers,
                    )
                except Exception:
                    pass

                session = requests.Session()
                global_value.low_level_reconnect_session[id(wss)] = session

                data = {
                    "identifier": global_value.account[id(wss)]["email"],
                    "password": global_value.account[id(wss)]["password"],
                    "token": None,
                }
                response = session.request(
                    method="POST",
                    url=profile.auth_base + "/api/v2/login",
                    data=data,
                    headers=headers,
                )
                try:
                    global_value.SSID[id(wss)] = response.cookies["ssid"]
                except Exception:
                    global_value.auto_reconnect[id(wss)] = False
                    _safe_release(wss)
                    return

                data = {"ssid": response.cookies["ssid"], "protocol": 3}
                wss.send(json.dumps(dict(name="authenticate", msg=data)))
                global_value.happen_close[id(wss)] = False

            _safe_release(wss)

        # --- anti-deadlock do ssl_Mutex (ver o bloco explicativo acima) ---

        def init_global_value(self, object_id):
            """init_global_value com o mutex seguro (a lib cria threading.Lock)."""
            original_init_global_value(self, object_id)
            global_value.ssl_Mutex[object_id] = _SafeMutex()

        def send_websocket_request(self, name, msg, request_id="", no_force_send=True):
            """send_websocket_request com acquire COM TIMEOUT.

            A lib fazia `ssl_Mutex.acquire()` sem timeout: com o lock retido
            por um callback quebrado, TODA chamada de send travava a thread
            do executor do asyncio — e o pool saturado derrubava o
            CONNECTOR inteiro (/health, /connections, /assets).
            """
            data = json.dumps(dict(name=name, msg=msg, request_id=request_id))

            def doing_send():
                if no_force_send is False:
                    self.websocket.send(data)
                    return
                mutex = global_value.ssl_Mutex.get(self.object_id)
                acquired = False
                if mutex is not None:
                    acquired = mutex.acquire(timeout=_SAFE_MUTEX_TIMEOUT)
                try:
                    self.websocket.send(data)
                finally:
                    if acquired and mutex is not None:
                        mutex.release()

            logger = logging.getLogger("iqoptionapi.api")
            try:
                doing_send()
            except Exception:
                self.connect()
                doing_send()
            logger.debug(data)

        def wsclient_on_message(self, ws, message):
            """on_message com try/finally — o lock nunca fica retido.

            O corpo original adquire no início e só libera no fim: uma
            exceção no meio (JSON inválido, ativo desconhecido) deixava o
            lock preso para sempre.
            """
            mutex = global_value.ssl_Mutex.get(self.api.object_id)
            if mutex is None:
                return original_on_message(self, ws, message)
            mutex.acquire(timeout=_SAFE_MUTEX_TIMEOUT)
            try:
                return original_on_message(self, ws, message)
            finally:
                # o corpo original libera em ponto fixo; se uma exceção
                # escapar, o nível fica órfão → force_release limpa tudo
                # que a thread ainda segura
                mutex.force_release()

        def wsclient_on_close(wss, close_status_code, close_msg):
            """on_close SEM o acquire que vazava o lock.

            A lib segurava o ssl_Mutex durante o run_forever() do
            auto-reconnect: com DNS quebrado ([Errno 11001] getaddrinfo
            failed) o lock ficava preso e todo send travava.
            """
            logger = logging.getLogger("iqoptionapi.ws.client")
            logger.debug("Websocket connection closed." + str(close_msg))
            global_value.check_websocket_if_connect[id(wss)] = 0
            if global_value.auto_reconnect.get(id(wss)) is True:
                global_value.happen_close[id(wss)] = True
                wss.sock = None
                wss.run_forever()

        # --- aplica os patches (marcador _quadcode p/ debugging/idempotência) ---
        for fn in (
            iq_option_init,
            iq_option_connect,
            profiled_iqoptionapi,
            login_post,
            twofa_post,
            logout_post,
            wsclient_init,
            wsclient_on_open,
            init_global_value,
            send_websocket_request,
            wsclient_on_message,
            wsclient_on_close,
        ):
            fn._quadcode = True  # type: ignore[attr-defined]

        stable_api.IQ_Option.__init__ = iq_option_init
        stable_api.IQ_Option.connect = iq_option_connect
        stable_api.IQOptionAPI = profiled_iqoptionapi
        Login._post = login_post
        _2FA._post = twofa_post
        Logout._post = logout_post
        IQOptionAPI.init_global_value = init_global_value
        IQOptionAPI.send_websocket_request = send_websocket_request
        ws_client.WebsocketClient.__init__ = wsclient_init
        ws_client.WebsocketClient.on_open = staticmethod(wsclient_on_open)
        ws_client.WebsocketClient.on_message = wsclient_on_message
        ws_client.WebsocketClient.on_close = staticmethod(wsclient_on_close)

        _APPLIED = True


def create_iq_option(
    email: Optional[str] = None,
    password: Optional[str] = None,
    ssid: Optional[str] = None,
    broker_profile: Optional[str] = None,
    host: Optional[str] = None,
    auto_logout: bool = True,
    **kwargs: Any,
):
    """
    Cria um IQ_Option com o perfil Quadcode aplicado (SSID opcional).

    Args:
        email/password: credenciais HTTP (ignoradas se o SSID for válido).
        ssid: session id pré-extraído — autentica sem senha via
            {"name": "authenticate", "msg": {"ssid": ..., "protocol": 3}}.
        broker_profile: "iqoption" | "polarium" (default: env BROKER_PROFILE).
        host: override do ws_host (usar junto com o perfil do broker).
    """
    apply_patches()
    from iqoptionapi.stable_api import IQ_Option

    return IQ_Option(
        email or "",
        password or "",
        set_ssid=ssid,
        auto_logout=auto_logout,
        host=host,
        broker_profile=broker_profile,
        **kwargs,
    )
