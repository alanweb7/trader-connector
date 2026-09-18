"""
Script de teste completo da API
Execute: python scripts/test_api.py
"""
import httpx
import json
import sys

BASE_URL = "http://localhost:8000"


def print_json(data, title=""):
    if title:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")
    print(json.dumps(data, indent=2, default=str))


def test_health():
    print("\n[1] Health Check...")
    r = httpx.get(f"{BASE_URL}/health")
    print_json(r.json(), "HEALTH")
    return r.status_code == 200


def test_create_connection():
    print("\n[2] Criando conexao com IQ Option...")
    r = httpx.post(f"{BASE_URL}/connections", json={
        "email": os.environ["IQOPTION_EMAIL"],
        "password": os.environ["IQOPTION_PASSWORD"],
        "account_type": "practice"
    }, timeout=60)
    print_json(r.json(), "CONNECTION CREATED")
    if r.status_code == 200:
        return r.json()["id"]
    else:
        print(f"Erro: {r.status_code}")
        return None


def test_balance(connection_id):
    print("\n[3] Obtendo saldo...")
    r = httpx.get(f"{BASE_URL}/connections/{connection_id}/balance", timeout=30)
    print_json(r.json(), "BALANCE")


def test_assets(connection_id):
    print("\n[4] Listando ativos...")
    r = httpx.get(f"{BASE_URL}/connections/{connection_id}/assets", timeout=120)
    data = r.json()
    print_json(data, "ASSETS")
    if "assets" in data:
        print(f"\n  Total: {len(data['assets'])} ativos")
    return data


def test_candles(connection_id, asset="EURUSD", timeframe=1, count=20):
    print(f"\n[5] Obtendo candles de {asset} (M{timeframe}, {count} candles)...")
    r = httpx.get(
        f"{BASE_URL}/connections/{connection_id}/candles",
        params={"asset": asset, "timeframe": timeframe, "count": count},
        timeout=120
    )
    data = r.json()
    print_json(data, f"CANDLES - {asset}")
    if "candles" in data:
        print(f"\n  Total: {len(data['candles'])} candles")
        if data["candles"]:
            last = data["candles"][-1]
            print(f"  Ultimo: O={last['open']} H={last['high']} L={last['low']} C={last['close']}")
    return data


def test_account(connection_id):
    print("\n[6] Informacoes da conta...")
    r = httpx.get(f"{BASE_URL}/connections/{connection_id}/account", timeout=30)
    print_json(r.json(), "ACCOUNT")


def test_status(connection_id):
    print("\n[7] Status da conexao...")
    r = httpx.get(f"{BASE_URL}/connections/{connection_id}/status", timeout=30)
    print_json(r.json(), "STATUS")


def test_events():
    print("\n[8] Historico de eventos...")
    r = httpx.get(f"{BASE_URL}/events?limit=10", timeout=30)
    print_json(r.json(), "EVENTS")


def main():
    print("=" * 60)
    print("  TESTE COMPLETO DO BROKER GATEWAY")
    print("=" * 60)

    # Testar health
    if not test_health():
        print("\nServidor NAO esta rodando!")
        print("Execute: python -m src.server")
        return

    # Criar conexao
    connection_id = test_create_connection()
    if not connection_id:
        print("\nNao foi possivel criar conexao")
        return

    print(f"\n  Connection ID: {connection_id}")

    # Testar dados
    test_status(connection_id)
    test_account(connection_id)
    test_balance(connection_id)
    
    # Tentar ativos (pode demorar ou retornar vazio se mercado fechado)
    try:
        assets_data = test_assets(connection_id)
        if assets_data and "assets" in assets_data:
            print(f"\n  Total: {len(assets_data['assets'])} ativos")
    except Exception as e:
        print(f"\n  Assets indisponivel (mercado pode estar fechado)")
        assets_data = None

    # Testar candles diretamente com EURUSD
    test_candles(connection_id, "EURUSD", 1, 20)

    test_events()

    print("\n" + "=" * 60)
    print("  TESTES CONCLUIDOS!")
    print("=" * 60)


if __name__ == "__main__":
    main()