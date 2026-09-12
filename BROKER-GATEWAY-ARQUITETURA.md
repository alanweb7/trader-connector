# Arquitetura Multi-Broker --- Broker Gateway

## 1. Objetivo

Construir uma camada de integração com brokers chamada **Broker
Gateway**, responsável por padronizar a comunicação do sistema com
diferentes brokers/plataformas de trading.

O sistema deve permitir adicionar ou remover brokers sem alterar o motor
de sinais, gerenciamento financeiro, frontend ou regras de negócio.

A primeira integração será com **IQ Option**. A arquitetura deve
permitir futuramente integrações como **Avalon**, Quotex, Pocket Option
e outros brokers que disponibilizem API, WebSocket ou mecanismos de
integração compatíveis.

> Importante: integrações com brokers devem respeitar os termos de uso,
> limites e mecanismos de autenticação de cada plataforma. Não assumir
> que uma biblioteca comunitária representa uma API oficial do broker.

------------------------------------------------------------------------

# 2. Princípio arquitetural

O sistema NÃO deve depender diretamente de uma biblioteca específica de
broker.

Errado:

``` text
Frontend
   ↓
Backend
   ↓
iqoptionapi
```

Correto:

``` text
Frontend
   ↓
Backend
   ↓
Broker Gateway
   ├── IQOptionAdapter
   ├── AvalonAdapter
   ├── QuotexAdapter
   └── OutrosAdapters
```

Cada adapter conhece os detalhes técnicos do respectivo broker.

O restante do sistema conhece somente a interface padronizada do
`Broker Gateway`.

------------------------------------------------------------------------

# 3. Arquitetura geral

``` text
┌─────────────────────────────────────────────┐
│                  FRONTEND                   │
│                                             │
│ React / Vite / PWA                          │
│ Dashboard / Sinais / Operações / Contas    │
└──────────────────────┬──────────────────────┘
                       │
                       │ REST / WebSocket
                       ▼
┌─────────────────────────────────────────────┐
│                 BACKEND                     │
│                 Node.js                     │
│                                             │
│ Usuários                                    │
│ Estratégias                                 │
│ Sinais                                      │
│ Gestão financeira                           │
│ Histórico                                   │
│ Regras de negócio                           │
└──────────────────────┬──────────────────────┘
                       │
                       │ REST / WebSocket
                       │ ou RabbitMQ
                       ▼
┌─────────────────────────────────────────────┐
│               BROKER GATEWAY                │
│                                             │
│ Interface comum para todos os brokers       │
│                                             │
│ Connection Manager                          │
│ Account Manager                             │
│ Market Data Manager                         │
│ Order Manager                               │
│ Result Manager                              │
│ Event Manager                               │
└───────────────┬──────────────┬──────────────┘
                │              │
                ▼              ▼
      ┌────────────────┐  ┌────────────────┐
      │ IQOptionAdapter │  │ AvalonAdapter  │
      └───────┬────────┘  └───────┬────────┘
              │                   │
              ▼                   ▼
        IQ Option             Avalon
```

------------------------------------------------------------------------

# 4. Responsabilidades

## Frontend

O frontend NÃO deve conhecer detalhes da API dos brokers.

Ele deve trabalhar com objetos padronizados:

``` json
{
  "broker": "iqoption",
  "account": "practice",
  "asset": "EURUSD-OTC",
  "timeframe": "M1"
}
```

------------------------------------------------------------------------

## Backend

Responsável por:

-   autenticação do usuário;
-   autorização;
-   estratégias;
-   sinais;
-   gerenciamento de risco;
-   regras de entrada;
-   gerenciamento de operações;
-   persistência;
-   auditoria;
-   comunicação com o Broker Gateway.

O backend não deve implementar diretamente o protocolo específico de um
broker.

------------------------------------------------------------------------

# 5. Broker Gateway

O Broker Gateway é a camada central de abstração.

Responsabilidades:

-   registrar adapters;
-   abrir conexões;
-   manter sessões;
-   reconectar;
-   controlar contas;
-   obter saldo;
-   obter ativos;
-   receber candles;
-   receber eventos;
-   enviar ordens;
-   consultar resultados;
-   normalizar erros;
-   normalizar respostas;
-   publicar eventos;
-   registrar logs;
-   isolar falhas de um broker dos demais.

------------------------------------------------------------------------

# 6. Interface padrão

Criar uma interface semelhante a:

``` typescript
interface BrokerAdapter {

  connect(config: BrokerConnectionConfig): Promise<ConnectionStatus>;

  disconnect(): Promise<void>;

  getStatus(): Promise<ConnectionStatus>;

  getAccount(): Promise<Account>;

  getBalance(): Promise<Balance>;

  getAssets(): Promise<Asset[]>;

  getAsset(asset: string): Promise<Asset>;

  getCandles(
    asset: string,
    timeframe: number,
    count: number
  ): Promise<Candle[]>;

  subscribeCandles(
    asset: string,
    timeframe: number,
    callback: CandleCallback
  ): Promise<Subscription>;

  unsubscribeCandles(
    subscriptionId: string
  ): Promise<void>;

  placeOrder(
    order: OrderRequest
  ): Promise<OrderResponse>;

  getOrder(
    orderId: string
  ): Promise<Order>;

  getOrderResult(
    orderId: string
  ): Promise<OrderResult>;

  cancelOrder(
    orderId: string
  ): Promise<void>;
}
```

A interface deve ser adaptada às capacidades reais de cada broker.

Não criar métodos falsos apenas para satisfazer a interface. Quando um
broker não oferecer determinada capacidade, retornar um erro padronizado
como `NOT_SUPPORTED`.

------------------------------------------------------------------------

# 7. Modelos padronizados

## Account

``` json
{
  "id": "account-id",
  "broker": "iqoption",
  "type": "practice",
  "currency": "BRL",
  "status": "connected"
}
```

## Balance

``` json
{
  "available": 100.00,
  "currency": "BRL",
  "updatedAt": "2026-09-12T02:00:00Z"
}
```

## Asset

``` json
{
  "symbol": "EURUSD-OTC",
  "name": "EUR/USD OTC",
  "type": "binary",
  "status": "open",
  "payout": 85
}
```

## Candle

``` json
{
  "asset": "EURUSD-OTC",
  "timeframe": "M1",
  "timestamp": 1757650000,
  "open": 1.1742,
  "high": 1.1748,
  "low": 1.1739,
  "close": 1.1746,
  "volume": null
}
```

## OrderRequest

``` json
{
  "asset": "EURUSD-OTC",
  "direction": "PUT",
  "amount": 10.00,
  "expiration": 1,
  "accountType": "practice"
}
```

## OrderResponse

``` json
{
  "id": "broker-order-id",
  "status": "accepted",
  "broker": "iqoption",
  "createdAt": "2026-09-12T02:10:00Z"
}
```

## OrderResult

``` json
{
  "orderId": "broker-order-id",
  "status": "closed",
  "result": "WIN",
  "profit": 8.50,
  "payout": 85,
  "closedAt": "2026-09-12T02:11:00Z"
}
```

------------------------------------------------------------------------

# 8. IQ Option Adapter

Criar:

``` text
adapters/
└── iqoption/
    ├── IQOptionAdapter
    ├── IQOptionClient
    ├── IQOptionSession
    ├── IQOptionWebSocket
    ├── IQOptionMarketData
    ├── IQOptionOrders
    └── IQOptionMapper
```

## Biblioteca

A primeira implementação pode utilizar uma biblioteca comunitária
adequada para IQ Option, encapsulada exclusivamente dentro do adapter.

Não permitir que o restante do projeto importe diretamente a biblioteca.

Exemplo:

``` text
Backend
   ↓
BrokerGateway
   ↓
IQOptionAdapter
   ↓
Biblioteca IQ Option
   ↓
IQ Option
```

Se a biblioteca for substituída futuramente, somente o adapter deve
precisar ser alterado.

------------------------------------------------------------------------

# 9. Avalon Adapter

Criar posteriormente:

``` text
adapters/
└── avalon/
    ├── AvalonAdapter
    ├── AvalonClient
    ├── AvalonSession
    ├── AvalonWebSocket
    ├── AvalonMarketData
    ├── AvalonOrders
    └── AvalonMapper
```

O adapter deve analisar primeiro qual mecanismo oficial ou tecnicamente
suportado pela Avalon está disponível:

-   REST;
-   WebSocket;
-   API oficial;
-   SDK oficial;
-   mecanismo de autenticação;
-   streaming de mercado;
-   execução de ordens.

Não reutilizar código da IQ Option presumindo que os protocolos sejam
iguais.

------------------------------------------------------------------------

# 10. Broker Registry

Criar um registro central:

``` typescript
BrokerRegistry.register(
  'iqoption',
  new IQOptionAdapter()
);

BrokerRegistry.register(
  'avalon',
  new AvalonAdapter()
);
```

Uso:

``` typescript
const broker = BrokerRegistry.get('iqoption');

await broker.connect(config);
```

O sistema não deve fazer:

``` typescript
if (broker === 'iqoption') {
   // código específico
}

if (broker === 'avalon') {
   // código específico
}
```

Esse tipo de lógica deve permanecer dentro dos adapters.

------------------------------------------------------------------------

# 11. Seleção do broker

O usuário poderá possuir várias conexões:

``` text
Usuário
│
├── IQ Option
│   ├── Practice
│   └── Real
│
└── Avalon
    └── Demo
```

A aplicação deve armazenar uma configuração por conexão.

Exemplo:

``` json
{
  "id": "connection-001",
  "userId": "user-001",
  "broker": "iqoption",
  "accountType": "practice",
  "enabled": true
}
```

Nunca armazenar senhas ou tokens em texto puro.

Utilizar secrets/criptografia apropriada.

------------------------------------------------------------------------

# 12. Multi-conta

O Gateway deve suportar várias conexões simultâneas:

``` text
Broker Gateway
│
├── Connection 001
│   └── IQ Option / User A / Practice
│
├── Connection 002
│   └── IQ Option / User B / Practice
│
├── Connection 003
│   └── Avalon / User C / Demo
│
└── Connection 004
    └── Outro Broker / User D
```

Cada conexão deve possuir:

-   sessão própria;
-   credenciais próprias;
-   estado próprio;
-   WebSocket próprio quando necessário;
-   fila própria quando necessário;
-   logs identificados;
-   isolamento de erros.

------------------------------------------------------------------------

# 13. Eventos

O Gateway deve normalizar eventos.

Exemplos:

``` text
broker.connected
broker.disconnected

account.updated
balance.updated

asset.opened
asset.closed

candle.created

order.created
order.accepted
order.rejected
order.closed

trade.win
trade.loss
```

Exemplo:

``` json
{
  "event": "trade.result",
  "broker": "iqoption",
  "connectionId": "connection-001",
  "orderId": "123456",
  "result": "WIN",
  "profit": 8.50
}
```

------------------------------------------------------------------------

# 14. RabbitMQ

Se o sistema já utilizar RabbitMQ, o Broker Gateway deve poder funcionar
de forma assíncrona.

Arquitetura:

``` text
Backend
   │
   ▼
RabbitMQ
   │
   ├── broker.commands
   │
   ├── broker.events
   │
   ├── broker.orders
   │
   └── broker.results
             │
             ▼
       Broker Gateway
```

Exemplo de comando:

``` json
{
  "command": "place_order",
  "connectionId": "connection-001",
  "requestId": "req-123",
  "data": {
    "asset": "EURUSD-OTC",
    "direction": "PUT",
    "amount": 10,
    "expiration": 1
  }
}
```

O Gateway responde através de evento:

``` json
{
  "event": "order.accepted",
  "requestId": "req-123",
  "orderId": "broker-order-123"
}
```

------------------------------------------------------------------------

# 15. Idempotência

Operações financeiras não podem ser duplicadas por causa de:

-   retry;
-   reconexão;
-   timeout;
-   mensagem duplicada;
-   reinício do worker;
-   falha de rede.

Toda ordem deve possuir:

``` text
requestId
idempotencyKey
connectionId
```

Antes de enviar uma ordem ao broker, verificar se a solicitação já foi
processada.

Nunca executar duas ordens para o mesmo `idempotencyKey`.

------------------------------------------------------------------------

# 16. Máquina de estados da ordem

Padronizar:

``` text
CREATED
   ↓
PENDING
   ↓
ACCEPTED
   ↓
OPEN
   ↓
CLOSED
   ↓
WIN / LOSS / DRAW
```

Possíveis falhas:

``` text
CREATED
   ↓
REJECTED

PENDING
   ↓
TIMEOUT

OPEN
   ↓
ERROR
```

Cada broker pode possuir estados diferentes.

O `Mapper` do adapter deve converter os estados do broker para os
estados internos.

------------------------------------------------------------------------

# 17. Gerenciamento de conexão

O connector deve implementar:

``` text
CONNECTING
   ↓
CONNECTED
   ↓
AUTHENTICATED
   ↓
READY
```

Em caso de falha:

``` text
READY
  ↓
DISCONNECTED
  ↓
RECONNECTING
  ↓
AUTHENTICATED
  ↓
READY
```

Implementar:

-   heartbeat;
-   timeout;
-   reconnect com backoff;
-   limite de tentativas;
-   renovação de sessão quando necessário;
-   limpeza de subscriptions;
-   recuperação após queda.

------------------------------------------------------------------------

# 18. Market Data

O market data deve ser independente do executor de ordens.

``` text
Market Data
     │
     ├── candles
     ├── ticks
     └── asset status
```

Isso permite que o sistema utilize os dados para:

-   indicadores;
-   estratégias;
-   geração de sinais;
-   backtesting;
-   monitoramento;

sem necessariamente executar uma ordem.

------------------------------------------------------------------------

# 19. Separação entre sinal e execução

O motor de estratégia gera:

``` text
M1;EURUSD-OTC;14:58;PUT
```

Ele NÃO deve executar diretamente.

Fluxo:

``` text
Strategy
   ↓
Signal Engine
   ↓
Risk Manager
   ↓
Execution Engine
   ↓
Broker Gateway
   ↓
Broker Adapter
   ↓
Broker
```

Exemplo:

``` json
{
  "asset": "EURUSD-OTC",
  "timeframe": "M1",
  "direction": "PUT",
  "entryTime": "14:58",
  "amount": 10
}
```

------------------------------------------------------------------------

# 20. Risk Manager

Antes de enviar uma ordem:

``` text
Sinal
 ↓
Verificar conta
 ↓
Verificar saldo
 ↓
Verificar ativo
 ↓
Verificar payout
 ↓
Verificar horário
 ↓
Verificar limite diário
 ↓
Verificar quantidade de operações
 ↓
Verificar exposição
 ↓
Autorizar execução
```

Somente depois:

``` text
Broker Gateway
```

O adapter nunca deve decidir regras estratégicas ou de gerenciamento
financeiro.

------------------------------------------------------------------------

# 21. Logs e auditoria

Registrar:

``` text
connectionId
userId
broker
account
requestId
orderId
asset
direction
amount
timestamp
status
error
result
```

Nunca registrar:

-   senha;
-   token de autenticação;
-   cookies de sessão;
-   secrets.

Os logs devem permitir reconstruir o ciclo:

``` text
SINAL
  ↓
AUTORIZAÇÃO
  ↓
COMANDO
  ↓
ENVIO
  ↓
ACEITE/REJEIÇÃO
  ↓
RESULTADO
```

------------------------------------------------------------------------

# 22. Segurança

Credenciais devem ficar fora do código.

Utilizar:

``` text
ENV
Secrets Manager
Vault
Docker Secrets
ou mecanismo equivalente
```

Separar:

``` text
PUBLIC CONFIG
PRIVATE CREDENTIALS
SESSION TOKENS
```

Nunca enviar credenciais para o frontend.

Nunca retornar tokens do broker através de endpoints públicos.

------------------------------------------------------------------------

# 23. Docker

O Broker Gateway deve ser independente:

``` text
docker-compose
│
├── backend
├── frontend
├── broker-gateway
├── rabbitmq
├── redis
└── postgres
```

Exemplo:

``` text
broker-gateway
    │
    ├── IQ Option
    ├── Avalon
    └── outros
```

O serviço deve poder ser atualizado/reiniciado sem derrubar o backend
principal.

------------------------------------------------------------------------

# 24. Estrutura sugerida do projeto

``` text
broker-gateway/
│
├── src/
│   │
│   ├── core/
│   │   ├── interfaces/
│   │   │   └── broker-adapter.ts
│   │   ├── models/
│   │   ├── errors/
│   │   ├── events/
│   │   └── registry/
│   │
│   ├── adapters/
│   │   │
│   │   ├── iqoption/
│   │   │   ├── adapter
│   │   │   ├── client
│   │   │   ├── session
│   │   │   ├── websocket
│   │   │   ├── market-data
│   │   │   ├── orders
│   │   │   └── mapper
│   │   │
│   │   └── avalon/
│   │       ├── adapter
│   │       ├── client
│   │       ├── session
│   │       ├── websocket
│   │       ├── market-data
│   │       ├── orders
│   │       └── mapper
│   │
│   ├── services/
│   │   ├── connection-manager
│   │   ├── account-manager
│   │   ├── market-manager
│   │   ├── order-manager
│   │   └── event-manager
│   │
│   ├── transport/
│   │   ├── http
│   │   ├── websocket
│   │   └── rabbitmq
│   │
│   └── main
│
├── tests/
├── Dockerfile
├── package.json
└── README.md
```

A implementação real pode ajustar essa estrutura à stack escolhida.

------------------------------------------------------------------------

# 25. API do Gateway

Endpoints mínimos:

``` http
GET /health

GET /brokers

GET /connections

POST /connections

DELETE /connections/:id

POST /connections/:id/connect

POST /connections/:id/disconnect

GET /connections/:id/status

GET /connections/:id/account

GET /connections/:id/balance

GET /connections/:id/assets

GET /connections/:id/candles

POST /connections/:id/orders

GET /connections/:id/orders/:orderId

GET /connections/:id/orders/:orderId/result
```

WebSocket:

``` text
/ws/connections/:id
```

Eventos:

``` text
candle
balance
order
trade
connection
error
```

------------------------------------------------------------------------

# 26. Desenvolvimento por etapas

Não implementar tudo de uma vez.

## Fase 1 --- Foundation

Criar:

-   Broker Gateway;
-   interface `BrokerAdapter`;
-   Registry;
-   modelos padronizados;
-   logs;
-   health check.

Sem execução de ordens.

------------------------------------------------------------------------

## Fase 2 --- IQ Option Connection

Implementar somente:

``` text
connect
disconnect
status
authentication
balance
```

Testar em conta de prática.

------------------------------------------------------------------------

## Fase 3 --- Market Data

Implementar:

``` text
assets
candles
streaming
reconnection
```

Validar M1 e M5.

------------------------------------------------------------------------

## Fase 4 --- Order Lifecycle

Implementar:

``` text
placeOrder
order status
result
WIN
LOSS
DRAW
```

Testar exclusivamente em conta de prática/demo quando disponível.

------------------------------------------------------------------------

## Fase 5 --- Backend Integration

Integrar:

``` text
Backend
   ↓
Broker Gateway
```

O motor de sinais ainda não deve enviar ordens automaticamente.

------------------------------------------------------------------------

## Fase 6 --- Execution Engine

Adicionar:

``` text
Signal
 ↓
Risk Manager
 ↓
Execution Engine
 ↓
Broker Gateway
```

------------------------------------------------------------------------

## Fase 7 --- Avalon

Somente depois de estabilizar o adapter IQ Option:

``` text
AvalonAdapter
```

Mapear suas APIs e capacidades reais para a interface comum.

------------------------------------------------------------------------

# 27. Testes obrigatórios

Criar testes para:

### Conexão

``` text
connect
disconnect
reconnect
invalid credentials
timeout
```

### Market Data

``` text
subscribe
unsubscribe
candle
connection loss
reconnection
```

### Orders

``` text
create
accept
reject
timeout
close
WIN
LOSS
DRAW
```

### Idempotência

``` text
mesma request
mesmo idempotencyKey
não duplicar ordem
```

### Multi-broker

``` text
IQ Option funcionando
Avalon funcionando
IQ Option indisponível
Avalon funcionando
```

Uma falha em um broker não pode derrubar os demais.

------------------------------------------------------------------------

# 28. Regra de ouro

O código de negócio deve ser agnóstico ao broker.

Não fazer:

``` typescript
if (broker === 'iqoption') {
    // estratégia
}
```

Nem:

``` typescript
if (broker === 'avalon') {
    // gerenciamento financeiro
}
```

O correto:

``` typescript
const broker = brokerGateway.get(connectionId);

await broker.placeOrder(order);
```

Toda particularidade deve ficar no adapter.

------------------------------------------------------------------------

# 29. Objetivo final

O sistema deverá chegar a:

``` text
                    TRADING SYSTEM
                          │
                          ▼
                   EXECUTION ENGINE
                          │
                          ▼
                    BROKER GATEWAY
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ▼                  ▼                  ▼
 IQOptionAdapter     AvalonAdapter      BrokerXAdapter
       │                  │                  │
       ▼                  ▼                  ▼
  IQ Option            Avalon             Broker X
```

Adicionar um novo broker deve significar principalmente:

``` text
1. Criar novo Adapter
2. Implementar BrokerAdapter
3. Criar mappers
4. Registrar no BrokerRegistry
5. Criar testes
```

O restante do sistema permanece inalterado.

------------------------------------------------------------------------

# 30. Instrução para o Agente IA

Você é responsável por implementar a arquitetura **Broker Gateway
Multi-Broker** descrita neste documento.

Regras:

1.  Não acople o sistema a um broker específico.
2.  Não misture lógica de estratégia com lógica de integração.
3.  Não misture gerenciamento de risco com adapter.
4.  Não expor credenciais no frontend.
5.  Não armazenar secrets em texto puro.
6.  Não executar ordens reais durante desenvolvimento sem autorização
    explícita.
7.  Priorizar conta de prática/demo para testes.
8.  Implementar idempotência para operações.
9.  Implementar reconexão segura.
10. Normalizar eventos, erros, candles, contas e resultados.
11. Isolar completamente cada broker através de adapters.
12. Não assumir que APIs comunitárias são APIs oficiais.
13. Antes de implementar um broker, verificar a documentação e o
    mecanismo de integração realmente disponível.
14. Não criar endpoints específicos de um broker no backend principal
    quando a funcionalidade puder ser abstraída pelo Gateway.
15. Manter logs e auditoria suficientes para rastrear cada operação.
16. Implementar primeiro a conexão IQ Option, depois market data, depois
    ciclo de ordem e somente então integração com o motor de sinais.
17. Após estabilizar IQ Option, criar o adapter da Avalon.
18. Não reescrever o sistema existente sem necessidade; integrar a
    arquitetura progressivamente.
19. Priorizar código modular, testável e substituível.
20. Cada adapter deve poder ser atualizado independentemente dos demais.

## Estratégia de implementação

Executar uma etapa por vez.

Primeiro:

``` text
Broker Gateway
+
BrokerAdapter
+
BrokerRegistry
+
IQOptionAdapter
+
connect/status/balance
```

Depois avançar somente após os testes dessa etapa passarem.

Não implementar todas as fases simultaneamente.
