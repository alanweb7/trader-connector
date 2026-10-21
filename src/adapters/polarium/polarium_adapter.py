"""
Adapter para Polarium Broker (white-label Quadcode).

Reusa todo o fluxo do IQOptionAdapter — a plataforma é a mesma (canais
"authenticate"/buy/buy-options idênticos); muda o perfil de endpoints
(ws.trade.polariumbroker.com / auth.trade.polariumbroker.com) e o nome
do broker nas respostas.

Conecta por SSID (sem senha) ou por email/senha:
    POST /connections
    {
      "broker": "polarium",
      "ssid": "SEU_SSID_AQUI",
      "account_type": "practice"
    }
"""
from ..iqoption.iqoption_adapter import IQOptionAdapter


class PolariumAdapter(IQOptionAdapter):
    """Polarium Broker — IQOptionAdapter sobre o perfil 'polarium'."""

    BROKER_NAME = "polarium"
    default_broker_profile = "polarium"
