# Broker Gateway

Multi-broker gateway para integração com plataformas de trading.

## Arquitetura

```
┌─────────────────────────────────────────────┐
│                  FRONTEND                   │
│            React / Vite / PWA               │
└──────────────────────┬──────────────────────┘
                       │
                       │ REST / WebSocket
                       ▼
┌─────────────────────────────────────────────┐
│              BROKER GATEWAY                 │
│                 FastAPI                     │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │         Broker Registry             │   │
│  │    ┌──────────────────────────┐     │   │
│  │    │     IQOptionAdapter      │     │   │
│  │    └──────────────────────────┘     │   │
│  └─────────────────────────────────────┘   │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │   IQ Option    │
              └────────────────┘
```

## Instalação

```bash
# Clonar repositório
git clone <repository-url>
cd broker-gateway

# Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# Instalar dependências
pip install -e .

# Copiar arquivo de exemplo
cp .env.example .env

# Editar .env com suas credenciais
```

## Configuração

Edite o arquivo `.env`:

```env
PORT=8000
HOST=0.0.0.0
IQOPTION_EMAIL=your_email@example.com
IQOPTION_PASSWORD=your_password
IQOPTION_ACCOUNT_TYPE=practice
```

**IMPORTANTE**: Use sempre conta de prática para testes!

## Executar

```bash
# Modo desenvolvimento
python -m src.server

# ou
uvicorn src.server:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Health Check
```
GET /health
```

### Brokers
```
GET /brokers
```

### Conexões
```
GET    /connections
POST   /connections
GET    /connections/{id}
DELETE /connections/{id}
POST   /connections/{id}/connect
POST   /connections/{id}/disconnect
GET    /connections/{id}/status
```

### Conta
```
GET /connections/{id}/account
GET /connections/{id}/balance
```

### Ativos
```
GET /connections/{id}/assets
GET /connections/{id}/assets/{symbol}
```

### Candles
```
GET /connections/{id}/candles?asset=EURUSD&timeframe=1&count=100
```

### Ordens
```
POST /connections/{id}/orders
GET  /connections/{id}/orders/{orderId}
GET  /connections/{id}/orders/{orderId}/result
```

### Eventos
```
GET /events?limit=100
```

## B3 via MetaTrader 5 (broker "mt5")

Fonte de dados da **B3** via API local `b3-mt5-api` rodando na VPS Windows ao
lado do terminal MT5. Ponte HTTP/WS — **somente dados**
(candles/cotações; sem ordens ou saldo).

**Catálogo curado: o módulo B3 expõe apenas 2 ativos** — `WIN` (Mini Ibovespa,
contrato vigente `WINZ26`) e `BIT` (Futuro de Bitcoin, contrato vigente
`BITX26`). O id é estável entre meses; a API MT5 resolve `WIN` → `WIN$`
(contínuo por liquidez, histórico muito maior) e devolve o contrato no nome.

```env
# .env do gateway (ou .env.portainer)
MT5_API_URL=http://<IP_DA_VPS_WINDOWS>:8001
```

Criar conexão (sem credenciais — a autenticação é a sessão do MT5):

```bash
curl -X POST http://localhost:8000/connections \
  -H "Content-Type: application/json" \
  -d '{"broker": "mt5", "name": "B3 Toro"}'
```

Depois disso `/connections/{id}/assets` devolve os 2 ativos do catálogo e
`/connections/{id}/candles` e `/ws/connections/{id}` funcionam igual aos demais
brokers (`?asset=WIN&timeframe=1&count=100`). Conexões `mt5` nunca assumem o
feed padrão de market data quando há IQ Option/Polarium ativa — na UI, escolha
a fonte no seletor **"Fonte de dados"** da página /mercado (envia
`connectionId` explícito; o gateway valida o escopo do usuário). Documentação
completa: `../MT5-API/docs/INTEGRACAO-B3.md`.

## Exemplos de Uso

### Criar Conexão

```bash
curl -X POST http://localhost:8000/connections \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your_email@example.com",
    "password": "your_password",
    "account_type": "practice"
  }'
```

### Obter Saldo

```bash
curl http://localhost:8000/connections/{connection_id}/balance
```

### Listar Ativos

```bash
curl http://localhost:8000/connections/{connection_id}/assets
```

### Obter Candles

```bash
curl "http://localhost:8000/connections/{connection_id}/candles?asset=EURUSD&timeframe=1&count=50"
```

### Enviar Ordem

```bash
curl -X POST http://localhost:8000/connections/{connection_id}/orders \
  -H "Content-Type: application/json" \
  -d '{
    "asset": "EURUSD",
    "direction": "CALL",
    "amount": 10,
    "expiration": 1
  }'
```

## Estrutura do Projeto

```
broker-gateway/
│
├── src/
│   ├── core/
│   │   ├── interfaces/    # Interfaces abstratas
│   │   ├── models/        # Modelos de dados
│   │   ├── errors/        # Erros padronizados
│   │   ├── events/        # Gerenciador de eventos
│   │   └── registry/      # Registro de adapters
│   │
│   ├── adapters/
│   │   └── iqoption/      # Adapter IQ Option
│   │
│   ├── services/          # Serviços
│   ├── transport/         # Transporte (HTTP, WS)
│   └── server.py          # Servidor FastAPI
│
├── tests/                 # Testes
├── pyproject.toml         # Configuração do projeto
├── .env.example           # Variáveis de ambiente
└── README.md              # Esta documentação
```

## Adapters

### IQ Option

O adapter IQ Option utiliza a biblioteca `iqoptionapi` para conexão com a plataforma.

**Funcionalidades:**
- Conexão com conta practice/real
- Obter saldo
- Listar ativos
- Obter candles históricos
- Enviar ordens

**Limitações:**
- Streaming de candles em tempo real (em desenvolvimento)
- Cancelamento de ordens (não suportado pelo broker)

## Desenvolvimento

### Adicionar Novo Broker

1. Criar pasta em `src/adapters/{broker_name}/`
2. Implementar interface `BrokerAdapter`
3. Criar mappers para modelos
4. Registrar no `BrokerRegistry`
5. Criar testes

### Testes

```bash
pytest
```

### Lint

```bash
ruff check .
```

### Type Check

```bash
mypy src/
```

## Segurança

- **NUNCA** armazene credenciais em texto puro em produção
- Use variáveis de ambiente ou secrets manager
- Use sempre conta de prática para testes
- Implemente autenticação adequada para endpoints

## Roadmap

- [x] Fase 1: Foundation
- [ ] Fase 2: IQ Option Connection
- [ ] Fase 3: Market Data (Streaming)
- [ ] Fase 4: Order Lifecycle
- [ ] Fase 5: Backend Integration
- [ ] Fase 6: Execution Engine
- [ ] Fase 7: Avalon Adapter

## Licença

MIT