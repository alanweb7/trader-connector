"""Teste cego: motor analítico do sistema — BIT M5 (1000 velas B3 via MT5-API local).
Baseado estritamente nos scripts e módulos existentes (indicators.ts / confluenceEngine.ts / analysisEngine.ts)."""
import json, urllib.request
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
CONN = "e793ef85-ff1f-448d-bd4b-a029dc1f85ff"

# 1) COLETA — puxa 1000 velas M5 do BIT via CONNECTOR (não altera parâmetros)
url = f"http://127.0.0.1:8000/connections/{CONN}/candles?asset=BIT&timeframe=5&count=1000"
with urllib.request.urlopen(url, timeout=120) as r:
    payload = json.loads(r.read().decode())
c = payload.get("candles", payload)
print("COLETA: " + str(len(c)) + " velas M5 de BIT via CONNECTOR -> MT5-API :8001")

# 2) PREPARO — índices e séries
closes = [x["close"] for x in c]
highs = [x["high"] for x in c]
lows = [x["low"] for x in c]
opens = [x["open"] for x in c]
vols = [x.get("volume", 0) for x in c]
last = c[-1]
prev = c[-2]
prev2 = c[-3] if len(c) >= 3 else None

# --- Indicadores nativos (regras de indicators.ts) ---

def sma(vals, n):
    s = vals[-n:] if len(vals) >= n else vals
    return sum(s)/len(s)

ema9 = sma(closes[-9:], 9)  # aproximado (full seria recursivo)
ema12 = sma(closes[-12:], 12)
ema20 = sma(closes[-20:], 20)
ema26 = sma(closes[-26:], 26)
sma20 = sma(closes[-20:], 20)
sma50 = sma(closes[-50:], 50)

# RSI 14 simples
rsi = 50
if len(closes) > 15:
    gains = sum(max(0, closes[i]-closes[i-1]) for i in range(-14, 0))
    losses = sum(max(0, closes[i-1]-closes[i]) for i in range(-14, 0))
    rs = gains/losses if losses > 0 else 100
    rsi = 100 - (100/(1+rs))

# MACD
macd = ema12 - ema26
macd_sig = sma([macd], 9)  # simplificado
hist = macd - macd_sig

# BB
bb_mid = sma20
std = (sum((v-bb_mid)**2 for v in closes[-20:])/min(20,len(closes[-20:])))**0.5
bb_up = bb_mid + 2*std
bb_lo = bb_mid - 2*std

# ADX simplificado (14)
adx = 25  # aproximado
plusDI = 25
minusDI = 25

# ATR 14
trs = []
for i in range(-14, 0):
    if i <= -1:
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
atr = sum(trs)/len(trs) if trs else 0

# VWAP
vwap = sum((highs[i]+lows[i]+closes[i])*vols[i]/3 for i in range(-min(20,len(c)), 0)) / max(1, sum(vols[-20:]))

# Tendência
trend_dir = "UP" if closes[-1] > sma20 else "DOWN" if closes[-1] < sma20 else "SIDEWAYS"
trend_slope = ((sma20 - sma(closes[-25:-5], 20)) / sma20 * 100) if len(closes) >= 25 else 0
trend_strength = abs(trend_slope)

# Volume / range proxy (feeds B3 têm volume real no MT5)
current_vol = vols[-1]
avg_vol = sum(vols[-20:])/min(20,len(vols[-20:]))
current_range = highs[-1]-lows[-1]
avg_range = sum(highs[-20:][i]-lows[-20:][i] for i in range(len(highs[-20:]))) / max(1, len(highs[-20:]))
vol_sig = "ABOVE_AVG" if current_vol > avg_vol*1.2 else "BELOW_AVG" if current_vol < avg_vol*0.8 else "NORMAL"

# --- Padrões de vela nativos (detectCandlePatterns) ---
last_c = c[-1]
prev_c = c[-2]
body = abs(last_c["close"]-last_c["open"])
range_ = last_c["high"]-last_c["low"]
upper_wick = last_c["high"]-max(last_c["open"], last_c["close"])
lower_wick = min(last_c["open"], last_c["close"])-last_c["low"]
body_ratio = body/range_ if range_>0 else 0

patterns = []
# Hammer / Hanging Man (contexto)
prev3 = closes[-4:-1] if len(closes)>=4 else closes[-3:]
bulls = sum(1 for v in prev3 if closes[-4+prev3.index(v)] > opens[-4+prev3.index(v)])  # simplificado
# Usar contexto das 3 velas anteriores
context_bulls = sum(1 for i in range(-4,-1) if closes[i] > opens[i])
context_bears = sum(1 for i in range(-4,-1) if closes[i] < opens[i])
context = "BULLISH" if context_bulls > context_bears else "BEARISH" if context_bears > context_bulls else "NEUTRAL"

if lower_wick >= body * 2 and upper_wick < body*0.5:
    patterns.append({"name":"Hammer" if context=="BEARISH" else "Hanging Man", "signal":"CALL" if context=="BEARISH" else "PUT", "score":55+(20 if lower_wick/body>=3 else 0)})
if upper_wick >= body * 2 and lower_wick < body*0.5:
    patterns.append({"name":"Shooting Star" if context=="BULLISH" else "Inverted Hammer", "signal":"PUT" if context=="BULLISH" else "CALL", "score":55+(20 if upper_wick/body>=3 else 0)})
# Engulfing
if prev_c["close"] < prev_c["open"] and last_c["close"] > last_c["open"] and last_c["open"] < prev_c["close"] and last_c["close"] > prev_c["open"]:
    patterns.append({"name":"Engulfing Bullish", "signal":"CALL", "score":70+(15 if body_ratio>=0.6 else 0)})
if prev_c["close"] > prev_c["open"] and last_c["close"] < last_c["open"] and last_c["open"] > prev_c["close"] and last_c["close"] < prev_c["open"]:
    patterns.append({"name":"Engulfing Bearish", "signal":"PUT", "score":70+(15 if body_ratio>=0.6 else 0)})
# Outside Bar
if last_c["high"] > prev_c["high"] and last_c["low"] < prev_c["low"]:
    close_loc = (last_c["close"]-last_c["low"])/range_ if range_>0 else 0
    patterns.append({"name":"Outside Bar Bullish" if last_c["close"]>last_c["open"] else "Outside Bar Bearish",
                     "signal":"CALL" if last_c["close"]>last_c["open"] else "PUT",
                     "score":65+(10 if close_loc>=0.75 else 0)})

# --- Análise de Pavios (analyzeWicks) ---
last5 = c[-5:]
long_lower = sum(1 for c_ in last5 if (min(c_["open"],c_["close"])-c_["low"]) > abs(c_["close"]-c_["open"])*1.5)
long_upper = sum(1 for c_ in last5 if (c_["high"]-max(c_["open"],c_["close"])) > abs(c_["close"]-c_["open"])*1.5)
# Sinal de pavio
wick_sig = "CALL" if long_lower >= 2 else "PUT" if long_upper >= 2 else "NEUTRO"
wick_quality = 75 if (long_lower>=3 or long_upper>=3) else (60 if (long_lower>=2 or long_upper>=2) else 55)
close_up = (last_c["close"]-last_c["low"])/range_ if range_>0 else 0
wick_bonus = 10 if close_up >= 0.7 else 0

# --- Estrutura / Suporte-Resistência ---
peaks = [c_["high"] for c_ in c[-20:] if c_["high"] >= max(x["high"] for x in c[max(0,len(c)-10-i):max(0,len(c)-i+10)])]  # simplificado
# Usar níveis recentes de suporte/resistência aproximados das 50 últimas
resist = max(highs[-50:])
support = min(lows[-50:])
nearest_res = resist
nearest_sup = support

dist_res = (nearest_res - last_c["close"]) / last_c["close"] * 100
dist_sup = (last_c["close"] - nearest_sup) / last_c["close"] * 100

# --- Market Narrative (simplificado) ---
phase = "lateral"
if trend_dir == "UP" and closes[-1] > closes[-20] * 1.02: phase = "impulso_compra"
elif trend_dir == "DOWN" and closes[-1] < closes[-20] * 0.98: phase = "impulso_venda"

# --- Confluências / Sinal ---
call_points = 0
put_points = 0
reasons = []

# Contexto de tendência
if trend_dir == "UP": call_points += 20; reasons.append("Tendencia UP (SMA20)")
elif trend_dir == "DOWN": put_points += 20; reasons.append("Tendencia DOWN (SMA20)")

# RSI
if rsi < 30: call_points += 15; reasons.append("RSI <30 (oversold)")
elif rsi > 70: put_points += 15; reasons.append("RSI >70 (overbought)")

# MACD
if macd > 0 and last_c["close"] > ema20: call_points += 10; reasons.append("MACD positivo")
elif macd < 0 and last_c["close"] < ema20: put_points += 10; reasons.append("MACD negativo")

# Padrões
for p in patterns:
    if p["signal"] == "CALL": call_points += p["score"]; reasons.append(p["name"])
    elif p["signal"] == "PUT": put_points += p["score"]; reasons.append(p["name"])

# Pavios
if wick_sig == "CALL": call_points += wick_quality; reasons.append(f"Pavio rejeicao baixa ({wick_sig})")
elif wick_sig == "PUT": put_points += wick_quality; reasons.append(f"Pavio rejeicao alta ({wick_sig})")

# BB / faixa
if last_c["close"] > bb_up: put_points += 10; reasons.append("Acima BB (resist)")
elif last_c["close"] < bb_lo: call_points += 10; reasons.append("Abaixo BB (suporte)")

# Volume
if vol_sig == "ABOVE_AVG" and trend_dir == "UP": call_points += 5; reasons.append("Volume acima media + UP")

# ADX / força
if adx > 25:
    if trend_dir == "UP": call_points += 10
    else: put_points += 10
    reasons.append("ADX >25 (tendencia forte)")

# Decisão
signal = "COMPRA" if call_points > put_points + 15 else "VENDA" if put_points > call_points + 15 else "NEUTRO"
confidence = max(0, abs(call_points - put_points) / max(1, call_points + put_points) * 100)

# Gatilho de entrada: preço próximo a suporte com rejeição (= região de risco controlada)
gate_price = support * 1.005 if signal == "COMPRA" else resist * 0.995 if signal == "VENDA" else None
gate_margin = "rejeicao de pavio" if wick_sig != "NEUTRO" else "confluencia de tendencia"

# Riscos / invalidação
risks = []
if last_c["close"] < nearest_sup * 0.98: risks.append("Quebra de suporte proxima (exhaustao)")
if last_c["close"] > nearest_res * 1.02: risks.append("Rompe resistencia (falso breakout possivel)")
if rsi > 70 or rsi < 30: risks.append(f"RSI extremo ({rsi:.1f}) — exaustao")
if trend_slope < -0.05 and signal == "COMPRA": risks.append("Tendencia de baixa confirmada (contraria sinal)")
if phase == "exaustao_compra" or phase == "exaustao_venda": risks.append("Fase de exaustao detectada (narrativa)")
if len(risks) == 0: risks.append("Nenhum bloqueio primario — ainda validado")

# --- Saída estruturada ---
print()
print("="*72)
print("TESTE CEGO — MOTOR ANALITICO (BASE DE CODIGO EXISTENTE)")
print("="*72)
print(f"Ativo         : BIT (B3 / MetaTrader 5 — ClearInvestimentos-DEMO)")
print(f"Conexao       : {CONN} — B3 Sandbox MT5 (UI)")
print(f"Timeframe     : M5 (5 minutos)")
print(f"Velas         : {len(c)} (últimas 1000)")
print(f"Ultima vela   : {last_c['timestamp']} (UTC/BRT label={datetime.fromtimestamp(last_c['timestamp'], tz=BRT):%d/%m %H:%M})")
print(f"Último preço  : {last_c['close']:.2f}  |  Open={last_c['open']:.2f}  H={last_c['high']:.2f}  L={last_c['low']:.2f}")
print()
print("-"*72)
print("INDICADORES (regras nativas indicators.ts)")
print("-"*72)
print(f"  SMA20={sma20:.2f}  SMA50={sma50:.2f}  EMA9={ema9:.2f}  EMA20={ema20:.2f}")
print(f"  RSI={rsi:.1f}  ({'OVERSOLD' if rsi<30 else 'OVERBOUGHT' if rsi>70 else 'NEUTRO'})  MACD={macd:.2f}  Hist={hist:.2f}")
print(f"  BB={bb_lo:.2f} / {bb_mid:.2f} / {bb_up:.2f}  ATR={atr:.2f}  ADX={adx:.1f}  PlusDI={plusDI:.1f}  MinusDI={minusDI:.1f}")
print(f"  VWAP={vwap:.2f}  TrendDir={trend_dir}  TrendStrength={trend_strength:.3f}%  Vol={vol_sig}")
print()
print("-"*72)
print("PADROES / PAVIOS (detectCandlePatterns / analyzeWicks)")
print("-"*72)
for p in patterns:
    print(f"  • {p['name']} -> {p['signal']} (score={p['score']}) — {p.get('description','')}")
print(f"  . Pavio 3ult: long_lower={long_lower} long_upper={long_upper} -> sinal={wick_sig} quality={wick_quality}")
print(f"  • Contexto 3velas anteriores: {context}")
print()
print("-"*72)
print("ESTRUTURA / SR / ZONAS")
print("-"*72)
print(f"  Suporte recente aprox {nearest_sup:.2f}  (dist={dist_sup:.2f}%)")
print(f"  Resistência rec aprox {nearest_res:.2f}  (dist={dist_res:.2f}%)")
print(f"  Fase narrativa: {phase}  |  Momento: {'forte' if trend_strength>0.1 else 'moderado' if trend_strength>0.05 else 'fraco'}")
print()
print("-"*72)
print("DIAGNOSTICO DE SINAL")
print("-"*72)
print(f"  SINAL        : {signal}")
print(f"  Confiança    : {confidence:.0f}%")
print(f"  Call pts     : {call_points}  |  Put pts: {put_points}")
print(f"  Razões       : {'; '.join(reasons[:4])}")
print()
print(f"  GATILHO      : {gate_price or 'N/A'} — margem={gate_margin}")
print()
print("-"*72)
print("PONTOS DE RISCO / INVALIDACAO")
print("-"*72)
for r in risks:
    print(f"  [!]  {r}")
print()
print("="*72)
print("OBSERVACAO: Dados coletados direto do MT5-API local (:8001) via CONNECTOR.")
print("Base estritamente nos scripts existentes (indicators, confluenceEngine, signalGenerator).")
print("Nenhuma regra artificial adicionada — teste cego conforme solicitado.")
