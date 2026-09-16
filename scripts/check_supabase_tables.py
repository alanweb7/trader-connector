#!/usr/bin/env python3
"""Verificar tabelas do Supabase do projeto gestao-financeira-trader"""
import os
os.environ['SUPABASE_URL'] = 'https://dytkmkydqatprzeshjns.supabase.co'
os.environ['SUPABASE_ANON_KEY'] = 'eyJhbG...4Kos'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'eyJhbG...VYr0'

from supabase import create_client
import inspect

# Verificar assinatura do create_client
sig = inspect.signature(create_client)
print(f"create_client signature: {sig}")

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_ROLE_KEY']

# Usar parâmetros posicionais
client = create_client(url, key)
print(f"Client criado: {type(client)}")
print(f"Client attributes: {[a for a in dir(client) if not a.startswith('_')]}")

print("=== TABELAS EXISTENTES ===")
try:
    # Listar todas as tabelas via RPC ou information_schema
    result = client.rpc('get_tables', {'schema': 'public'})
    print(f"RPC get_tables: {result}")
except Exception as e:
    print(f"RPC get_tables falhou: {e}")

# Tentar via REST direto
try:
    result = client.table('information_schema.tables').select('table_name').eq('table_schema', 'public').execute()
    print(f"\ninformation_schema.tables: {result.data}")
except Exception as e:
    print(f"information_schema falhou: {e}")

# Tentar listar tabelas conhecidas
known_tables = ['simulations', 'history', 'settings', 'analysis_outcomes', 'market_patterns', 'knowledge_base', 'signals', 'connector_configs']
print("\n=== VERIFICANDO TABELAS CONHECIDAS ===")
for table in known_tables:
    try:
        result = client.table(table).select('*').limit(1).execute()
        if result.data is not None:
            print(f"  ✓ {table}: existe (data: {len(result.data)} rows)")
        else:
            print(f"  ✗ {table}: não existe ou erro")
    except Exception as e:
        print(f"  ✗ {table}: erro - {str(e)[:50]}")

print("\n=== TABELAS DO PUBLIC ===")
try:
    # Lista todas as tabelas que existem
    tables_info = client.rpc('pg_tables', {'schema': 'public'}).execute()
    print(tables_info)
except:
    pass
