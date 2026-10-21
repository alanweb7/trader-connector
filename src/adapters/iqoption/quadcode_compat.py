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
                    global_value.ssl_Mutex[id(wss)].release()
                    return

                data = {"ssid": response.cookies["ssid"], "protocol": 3}
                wss.send(json.dumps(dict(name="authenticate", msg=data)))
                global_value.happen_close[id(wss)] = False

            global_value.ssl_Mutex[id(wss)].release()

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
        ):
            fn._quadcode = True  # type: ignore[attr-defined]

        stable_api.IQ_Option.__init__ = iq_option_init
        stable_api.IQ_Option.connect = iq_option_connect
        stable_api.IQOptionAPI = profiled_iqoptionapi
        Login._post = login_post
        _2FA._post = twofa_post
        Logout._post = logout_post
        ws_client.WebsocketClient.__init__ = wsclient_init
        ws_client.WebsocketClient.on_open = staticmethod(wsclient_on_open)

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
