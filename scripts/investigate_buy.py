"""
Investigar a assinatura e implementação do buy() e métodos relacionados na biblioteca iqoptionapi.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

from iqoptionapi.stable_api import IQ_Option
import inspect

print("=" * 60)
print("INVESTIGAÇÃO DO MÉTODO buy() E RELACIONADOS")
print("=" * 60)

# Listar métodos relacionados ao buy
api_methods = [m for m in dir(IQ_Option) if 'buy' in m.lower() or 'order' in m.lower() or 'expir' in m.lower()]
print("\n Métodos encontrados:")
for m in api_methods:
    print(f"   - {m}")

# Obter fontes
methods_to_investigate = [
    'buy',
    'buy_by_raw_expirations',
    'buy_digital',
    'buy_digital_spot',
    'buy_digital_spot_v2',
    'buy_multi',
    'buy_order',
    'cancel_order',
    'change_order',
    'get_order',
    'get_async_order',
    'check_binary_order',
    'get_betinfo',
]

for method_name in methods_to_investigate:
    if hasattr(IQ_Option, method_name):
        print(f"\n{'='*60}")
        print(f"MÉTODO: {method_name}")
        print(f"{'='*60}")
        
        method = getattr(IQ_Option, method_name)
        
        # Assinatura
        try:
            sig = inspect.signature(method)
            print(f" Assinatura: {sig}")
        except Exception as e:
            print(f" Assinatura indisponível: {e}")
        
        # Docstring
        doc = inspect.getdoc(method)
        if doc:
            print(f"\n Docstring:\n{doc}")
        
        # Fonte (limitada)
        try:
            source = inspect.getsource(method)
            lines = source.splitlines()
            print(f"\n Código (primeiras 60 linhas):")
            for line in lines[:60]:
                print(f"   {line}")
            if len(lines) > 60:
                print(f"   ... ({len(lines) - 60} linhas a mais)")
        except Exception as e:
            print(f"\n Código indisponível: {e}")

# Investigação adicional: verificar se há constantes ou enums de expirations
print(f"\n{'='*60}")
print(" CONSTANTES E VARIÁVEIS RELACIONADAS A EXPIRATION")
print(f"{'='*60}")

# Verificar atributos da classe que podem ser enums de expirations
for attr_name in dir(IQ_Option):
    if any(k in attr_name.lower() for k in ['expir', 'time', 'duration', 'period']):
        try:
            val = getattr(IQ_Option, attr_name)
            if not callable(val) and not attr_name.startswith('_'):
                print(f"   {attr_name} = {val!r}")
        except:
            pass

# Tentar instanciar e verificar atributos de instância relacionados
print("\n Criando instância para verificar atributos de instância...")
api = IQ_Option("dummy@dummy.com", "dummy")
for attr_name in dir(api):
    if any(k in attr_name.lower() for k in ['expir', 'time', 'duration', 'period', 'server']):
        try:
            val = getattr(api, attr_name)
            if not callable(val):
                print(f"   {attr_name} = {val!r}")
        except:
            pass

print("\n" + "=" * 60)
print("INVESTIGAÇÃO CONCLUÍDA")
print("=" * 60)
