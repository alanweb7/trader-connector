"""
Fluxo completo: conectar → place_order AUDCAD-OTC → aguardar resultado → capturar WIN/LOSS/DRAW.
Apenas conta de prática. 1 unidade. 1 minuto.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

EMAIL = os.environ["IQOPTION_EMAIL"]  # defina antes de executar
PASSWORD = os.environ["IQOPTION_PASSWORD"]  # defina antes de executar
from iqoptionapi.stable_api import IQ_Option, OP_code

AUDCAD_OTC_CODE = OP_code.ACTIVES['AUDCAD-OTC']  # 86

print("=" * 60)
print("FLUXO COMPLETO: place_order + resultado")
print("Ativo: AUDCAD-OTC (código 86)")
print("=" * 60)

api = IQ_Option(EMAIL, PASSWORD)

try:
    print("\n[1] Conectando...")
    api.connect()
    print(f"    check_connect: {api.check_connect()}")
    print(f"    balance: {api.get_balance()}")

    print("\n[2] Escolhendo direção...")
    # Alternar entre CALL e PUT a cada execução para não ficar sempre no mesmo lado
    import hashlib, hmac
    seed = int(time.time() / 60)  # mudar a cada minuto
    direction = "CALL" if (seed % 2 == 0) else "PUT"
    print(f"    Direção: {direction} (seed={seed})")
    expiration = 1  # minuto
    amount = 1  # unidade

    print("\n[3] Enviando buy()...")
    t0 = time.time()
    api.api.buy_multi_option = {}
    api.api.buy_successful = None
    req_id = str(int(time.time() * 1000) % 100000)
    
    api.api.buyv3(amount, AUDCAD_OTC_CODE, direction, expiration, req_id)
    
    order_id = None
    result = None
    while time.time() - t0 < 5:
        try:
            d = api.api.buy_multi_option.get(req_id, {})
            if 'message' in d:
                result = d['message']
                print(f"    Resposta: {result}")
                break
            if 'id' in d:
                order_id = d['id']
                result = api.api.result
                print(f"    ordem aceita! id={order_id}, result={result}")
                break
        except:
            pass
        time.sleep(0.1)
    
    if not order_id:
        print("    FALHA: ordem não aceita")
        print(f"    Resultado: {result}")
        raise SystemExit(1)

    print(f"\n[4] Aguardando expiração + verificação de resultado ({expiration}min)...")
    print(f"    order_id={order_id}")
    print(f"    aguardando {expiration} minuto(s) + tempo de processamento...")
    
    # Aguardar a expiração
    time.sleep(expiration * 60 + 15)  # 1min + 15s buffer
    
    # Métodos de verificação de resultado
    print("\n[5] Verificando resultado com múltiplos métodos...")
    
    # Método 1: check_win (para opções binárias)
    check_methods = [
        ('check_win', lambda oid: api.check_win(oid)),
        ('check_win_v2', lambda oid: api.check_win_v2(oid)),
        ('check_win_v3', lambda oid: api.check_win_v3(oid)),
        ('check_win_v4', lambda oid: api.check_win_v4(oid)),
        ('check_binary_order', lambda oid: api.check_binary_order(oid)),
        ('get_betinfo', lambda oid: api.get_betinfo(oid)),
    ]
    
    for name, func in check_methods:
        if not hasattr(api, name):
            print(f"    [{name}]: método não existe")
            continue
        try:
            t1 = time.time()
            resp = func(order_id)
            dt = time.time() - t1
            print(f"    [{name}]: {resp} (em {dt:.2f}s)")
        except Exception as e:
            print(f"    [{name}]: erro: {type(e).__name__}: {e}")

    # Método extra: get_positions, get_position
    print("\n[6] Outros métodos de posição...")
    for attr in ['get_positions', 'get_position', 'get_position_history', 'get_live_deal', 'get_optioninfo']:
        if hasattr(api, attr):
            try:
                resp = getattr(api, attr)()
                if resp:
                    print(f"    [{attr}]: {resp}")
            except Exception as e:
                print(f"    [{attr}]: erro: {e}")

    print("\n[7] Conclusão:")
    print(f"    order_id: {order_id}")
    print(f"    direction: {direction}")
    print(f"    ativo: AUDCAD-OTC")
    print(f"    resultado.raw: {result}")

finally:
    print("\n[8] Desconectando...")
    try:
        if hasattr(api, 'logout'):
            api.logout()
            print("    logout() executado")
        elif hasattr(api, 'disconnect'):
            api.disconnect()
            print("    disconnect() executado")
    except Exception as e:
        print(f"    erro: {e}")
    print("FIM")
