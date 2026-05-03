# -*- coding: utf-8 -*-
# ABSOLUTE_ULTIMATE_BOT_FINAL.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import threading
import json
import websocket
import asyncio
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request
from collections import defaultdict

# ============================================================
# 1. КОНФИГУРАЦИЯ
# ============================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# Загрузка 300+ монет с MEXC
def load_all_coins():
    try:
        r = requests.get("https://api.mexc.com/api/v3/exchangeInfo", timeout=15)
        if r.status_code == 200:
            symbols = []
            for s in r.json().get("symbols", []):
                if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
                    symbols.append(s.get("symbol"))
            return symbols[:300]
    except:
        pass
    return [
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
        "AVAXUSDT","DOTUSDT","LINKUSDT","MATICUSDT","UNIUSDT","ATOMUSDT","LTCUSDT",
        "ETCUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","FILUSDT","SUIUSDT",
        "SEIUSDT","TRXUSDT","XLMUSDT","VETUSDT","HBARUSDT","ICPUSDT","EGLDUSDT",
        "THETAUSDT","SANDUSDT","MANAUSDT","GALAUSDT","AXSUSDT","RNDRUSDT","IMXUSDT",
        "STXUSDT","MKRUSDT","CRVUSDT","SNXUSDT","COMPUSDT","ZECUSDT","DASHUSDT",
        "XMRUSDT","EOSUSDT","XTZUSDT","KSMUSDT","WAVESUSDT","ALGOUSDT","FLOWUSDT"
    ]

COINS = load_all_coins()
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

# Параметры
MAX_POSITIONS = 5
BUDGET_SHARE = 0.20
MIN_TRADE_USD = 5
RSI_BUY = 35
RSI_SELL = 65
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2
STOP_LOSS = 3.5
TAKE_PROFIT = 7.0
TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0
SCAN_INTERVAL = 10

# Фьючерсы
FUTURES_ENABLED = True
FUTURES_LEVERAGE = 3
FUTURES_BALANCE = 0

# Глобальные переменные
balance = 0.0
positions = []
signals = {}
logs = []
history = []
auto_pilot = True
running = True
last_daily_report = None

# ============================================================
# 2. API ФУНКЦИИ
# ============================================================

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_balance():
    try:
        t = int(time.time()*1000)
        sig = sign(f"timestamp={t}")
        r = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            for b in r.json().get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except: pass
    return 0

def get_futures_balance():
    try:
        t = int(time.time()*1000)
        sig = sign(f"timestamp={t}")
        r = requests.get(f"https://api.mexc.com/api/v3/futures/account?timestamp={t}&signature={sig}",
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("free", 0))
    except: pass
    return 0

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except: pass
    return 0

def get_klines(s, timeframe="5m", limit=100):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={s}&interval={timeframe}&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except: pass
    return []

# ============================================================
# 3. ВСЕ ИНДИКАТОРЫ (RSI, MACD, BOLLINGER)
# ============================================================

def calculate_rsi(prices, period=14):
    if len(prices) < period+1: return 50
    gains, losses = [], []
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0: gains.append(diff)
        else: losses.append(abs(diff))
    ag = sum(gains)/period if gains else 0
    al = sum(losses)/period if losses else 0.001
    return 100 - (100/(1+ag/al))

def calculate_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow: return 0, 0, 0
    ema_fast = sum(prices[-fast:]) / fast
    ema_slow = sum(prices[-slow:]) / slow
    macd_line = ema_fast - ema_slow
    macd_signal = sum(prices[-signal:]) / signal if signal > 0 else macd_line
    histogram = macd_line - macd_signal
    return macd_line, macd_signal, histogram

def calculate_bollinger(prices, period=20, std_dev=2):
    if len(prices) < period: return 0, 0, 0
    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    position = (prices[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return position, upper, lower

def multi_timeframe_confirm(symbol):
    scores = 0
    for tf in TIMEFRAMES[:3]:
        prices = get_klines(symbol, tf, 50)
        if len(prices) < 30: continue
        rsi = calculate_rsi(prices)
        if rsi < RSI_BUY: scores += 1
        elif rsi > RSI_SELL: scores -= 1
    return scores >= 2

def analyze_full(symbol, price):
    prices = get_klines(symbol, "5m", 100)
    if len(prices) < 50:
        return "HOLD", 0, 50, {}
    
    rsi = calculate_rsi(prices)
    macd, macd_signal, macd_hist = calculate_macd(prices)
    bb_pos, bb_upper, bb_lower = calculate_bollinger(prices)
    
    score = 0
    reasons = []
    
    if rsi < RSI_BUY:
        score += 40
        reasons.append(f"RSI={rsi:.0f} (перепроданность)")
    elif rsi > RSI_SELL:
        score -= 40
        reasons.append(f"RSI={rsi:.0f} (перекупленность)")
    
    if macd > macd_signal:
        score += 25
        reasons.append("MACD бычий")
    elif macd < macd_signal:
        score -= 25
        reasons.append("MACD медвежий")
    
    if bb_pos < 0.2:
        score += 30
        reasons.append("Цена у нижней полосы")
    elif bb_pos > 0.8:
        score -= 30
        reasons.append("Цена у верхней полосы")
    
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    if sma5 > sma20:
        score += 15
        reasons.append("Восходящий тренд")
    elif sma5 < sma20:
        score -= 15
        reasons.append("Нисходящий тренд")
    
    if multi_timeframe_confirm(symbol):
        if score > 0: score += 10
        if score < 0: score -= 10
        reasons.append("Подтверждено на нескольких ТФ")
    
    if score > 35:
        confidence = min(95, 60 + score)
        return "BUY", confidence, rsi, {"score": score, "reasons": reasons, "macd": macd, "bb_pos": bb_pos}
    elif score < -35:
        confidence = min(95, 60 + abs(score))
        return "SELL", confidence, rsi, {"score": score, "reasons": reasons, "macd": macd, "bb_pos": bb_pos}
    return "HOLD", 0, rsi, {"score": score, "reasons": reasons}

# ============================================================
# 4. ТОРГОВЛЯ
# ============================================================

def futures_open_long(symbol, amount_usd, leverage):
    try:
        price = get_price(symbol)
        if price <= 0: return False
        qty = round((amount_usd * leverage) / price, 6)
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&leverage={leverage}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/futures/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def futures_open_short(symbol, amount_usd, leverage):
    try:
        price = get_price(symbol)
        if price <= 0: return False
        qty = round((amount_usd * leverage) / price, 6)
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={qty}&leverage={leverage}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/futures/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def market_buy(symbol, amount_usd):
    try:
        price = get_price(symbol)
        if price <= 0: return False
        if price < 1:
            qty = int(amount_usd / price)
            if qty < 1: return False
        else:
            qty = round(amount_usd / price, 6)
            if qty < 1e-6: return False
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def market_sell(symbol, qty):
    try:
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={qty}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:400]}, timeout=3)
    except: pass

def add_log(msg):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(logs) > 100: logs.pop()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def add_history(symbol, side, price, amount, profit=0):
    history.insert(0, {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "symbol": symbol, "side": side, "price": round(price, 6),
                       "amount": round(amount, 2), "profit": round(profit, 2)})
    if len(history) > 100: history.pop()

# ============================================================
# 5. БЭКТЕСТИНГ
# ============================================================

def backtest_strategy(symbol, days=30):
    prices = get_klines(symbol, "5m", days * 288)
    if len(prices) < 100: return None
    
    balance_test = 1000
    positions_test = []
    trades = 0
    wins = 0
    
    for i in range(50, len(prices) - 10):
        recent = prices[:i]
        rsi = calculate_rsi(recent)
        macd, macd_sig, _ = calculate_macd(recent)
        bb_pos, _, _ = calculate_bollinger(recent)
        
        score = 0
        if rsi < RSI_BUY: score += 40
        if macd > macd_sig: score += 25
        if bb_pos < 0.2: score += 30
        
        if score > 35 and not positions_test:
            invest = balance_test * 0.2
            positions_test.append({"entry": prices[i], "invested": invest})
            balance_test -= invest
            trades += 1
        elif positions_test and (prices[i] >= positions_test[0]["entry"] * (1 + TAKE_PROFIT/100) or
                                 prices[i] <= positions_test[0]["entry"] * (1 - STOP_LOSS/100)):
            profit = (prices[i] - positions_test[0]["entry"]) / positions_test[0]["entry"] * 100
            profit_usd = positions_test[0]["invested"] * profit / 100
            balance_test += positions_test[0]["invested"] + profit_usd
            if profit > 0: wins += 1
            positions_test = []
    
    return {
        "final_balance": round(balance_test, 2),
        "profit": round(balance_test - 1000, 2),
        "profit_pct": round((balance_test - 1000) / 10, 1),
        "trades": trades,
        "wins": wins,
        "winrate": round(wins / trades * 100, 1) if trades > 0 else 0
    }

# ============================================================
# 6. ЕЖЕДНЕВНЫЙ ОТЧЁТ
# ============================================================

def daily_report():
    global last_daily_report
    today = datetime.now().date()
    if last_daily_report == today: return
    last_daily_report = today
    
    daily_profit = sum(h["profit"] for h in history if h["time"].startswith(str(today)))
    msg = f"📊 ЕЖЕДНЕВНЫЙ ОТЧЁТ {today}\n"
    msg += f"💰 Баланс: ${balance:.2f}\n"
    msg += f"📈 Прибыль за день: ${daily_profit:.2f}\n"
    msg += f"🏆 Сделок: {len([h for h in history if h['time'].startswith(str(today))])}\n"
    msg += f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}"
    send_telegram(msg)
    add_log(f"📊 Отчёт отправлен в Telegram")

# ============================================================
# 7. АВТОМАТИЧЕСКАЯ ТОРГОВЛЯ
# ============================================================

def get_position(symbol):
    for p in positions:
        if p["symbol"] == symbol: return p
    return None

def auto_trade():
    global balance, positions
    if not auto_pilot: return
    if len(positions) >= MAX_POSITIONS: return
    invest = max(balance * BUDGET_SHARE, MIN_TRADE_USD)
    if invest < MIN_TRADE_USD or invest > balance: return
    
    candidates = []
    for sym, data in signals.items():
        if data["signal"] == "BUY" and get_position(sym) is None:
            candidates.append((sym, data["price"], data["confidence"], data["details"]))
    
    if not candidates: return
    candidates.sort(key=lambda x: x[1])
    best_sym, best_price, best_conf, details = candidates[0]
    
    if best_price <= 0: return
    if best_price < 1:
        qty = int(invest / best_price)
        if qty < 1: return
        actual = qty * best_price
    else:
        qty = invest / best_price
        actual = invest
    
    if market_buy(best_sym, actual):
        balance -= actual
        positions.append({
            "symbol": best_sym,
            "entry_price": best_price,
            "invested": actual,
            "quantity": qty,
            "entry_time": time.time(),
            "peak_price": best_price,
            "peak_profit": 0,
            "confidence": best_conf,
            "details": details
        })
        add_log(f"🟢 АВТОПОКУПКА {best_sym}: ${actual:.2f} ({details['reasons'][0]})")
        send_telegram(f"🟢 ПОКУПКА {best_sym}: ${actual:.2f}")

def check_trailing_stop():
    global balance, positions
    to_remove = []
    for pos in positions:
        price = get_price(pos["symbol"])
        if price <= 0: continue
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            if pos["peak_profit"] - profit >= TRAILING_DISTANCE:
                if market_sell(pos["symbol"], pos["quantity"]):
                    profit_usd = pos["invested"] * profit / 100
                    balance += pos["invested"] + profit_usd
                    add_log(f"🎯 ТРЕЙЛИНГ-СТОП {pos['symbol']}: {profit:+.2f}% (+${profit_usd:.2f})")
                    add_history(pos["symbol"], "ТРЕЙЛИНГ-СТОП", price, pos["invested"], profit_usd)
                    to_remove.append(pos)
                continue
        
        if profit >= TAKE_PROFIT:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"🎉 ТЕЙК-ПРОФИТ {pos['symbol']}: {profit:+.2f}% (+${profit_usd:.2f})")
                add_history(pos["symbol"], "ТЕЙК-ПРОФИТ", price, pos["invested"], profit_usd)
                to_remove.append(pos)
            continue
        
        if profit <= -STOP_LOSS:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"🛑 СТОП-ЛОСС {pos['symbol']}: {profit:+.2f}% (${profit_usd:.2f})")
                add_history(pos["symbol"], "СТОП-ЛОСС", price, pos["invested"], profit_usd)
                to_remove.append(pos)
            continue
    
    for pos in to_remove:
        positions.remove(pos)

# ============================================================
# 8. ВЕБ-ИНТЕРФЕЙС
# ============================================================

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>ABSOLUTE ULTIMATE BOT</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:radial-gradient(circle at 20% 30%, #0a0f0a, #030603);color:#0f0;font-family:'Courier New',monospace;padding:20px}
        .container{max-width:1600px;margin:auto}
        .header{text-align:center;border-bottom:2px solid #0f0;margin-bottom:25px;padding-bottom:15px}
        h1{font-size:2rem;text-shadow:0 0 8px #0f0}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:20px;margin-bottom:20px}
        .card{background:rgba(10,20,5,0.75);border:1px solid #0f0;border-radius:20px;padding:20px}
        .card h3{border-left:4px solid #0f0;padding-left:12px;margin-bottom:16px}
        .stat{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a4a2a}
        .big-number{font-size:2.5rem;font-weight:bold;text-align:center;margin:15px 0}
        .btn{background:#0f0;color:#000;border:none;padding:8px 18px;margin:5px;cursor:pointer;border-radius:40px;font-weight:bold}
        .btn:hover{transform:scale(1.02);box-shadow:0 0 15px #0f0}
        .btn-danger{background:#f33;color:#fff}
        table{width:100%;border-collapse:collapse}
        th,td{padding:8px 5px;border-bottom:1px solid #2a4a2a;text-align:left}
        .signal-buy{color:#8f8;background:#0a2a0a;padding:2px 8px;border-radius:20px;display:inline-block}
        .profit{color:#8f8}.loss{color:#f88}
        .log-panel{background:#030603;height:200px;overflow:auto;border-radius:16px;padding:12px;font-size:12px}
        .footer{text-align:center;margin-top:30px;color:#5a7a5a;font-size:11px}
    </style>
</head>
<body>
<div class="container">
<div class="header">
    <h1>🧠 ABSOLUTE ULTIMATE BOT</h1>
    <p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
    <span class="badge">📊 МОНЕТ</span>
    <span class="badge">⚡ RSI+MACD+BB</span>
</div>

<div class="grid">
    <div class="card">
        <h3>💰 ПОРТФЕЛЬ</h3>
        <div class="big-number" id="balance">$0.00</div>
        <div class="stat"><span>Автопилот:</span><span id="autopilot">✅ ВКЛ</span></div>
        <div class="stat"><span>Позиций:</span><span id="pos_count">0</span></div>
        <div class="stat"><span>Сделок:</span><span id="total_trades">0</span></div>
        <div class="stat"><span>Прибыль:</span><span id="total_profit">$0.00</span></div>
        <button class="btn" onclick="fetch('/cmd/auto')">🤖 АВТОПИЛОТ</button>
        <button class="btn btn-danger" onclick="fetch('/cmd/close')">🔒 ЗАКРЫТЬ ВСЁ</button>
    </div>
    <div class="card">
        <h3>📈 БЫСТРЫЕ ДЕЙСТВИЯ</h3>
        <button class="btn" onclick="showBuy()">🟢 КУПИТЬ</button>
        <button class="btn" onclick="showSell()">🔴 ПРОДАТЬ</button>
        <button class="btn" onclick="runBacktest()">🔬 БЭКТЕСТ</button>
        <div class="stat"><span>BTC:</span><span id="btc">$---</span></div>
        <div class="stat"><span>ETH:</span><span id="eth">$---</span></div>
        <div class="stat"><span>SOL:</span><span id="sol">$---</span></div>
    </div>
</div>

<div class="grid">
    <div class="card">
        <h3>🎯 СИГНАЛЫ (RSI+MACD+BB)</h3>
        <div style="max-height:350px;overflow:auto"><table id="signals_table"></table></div>
    </div>
    <div class="card">
        <h3>📊 ПОЗИЦИИ</h3>
        <div style="max-height:350px;overflow:auto"><table id="positions_table"></table></div>
    </div>
</div>

<div class="card">
    <h3>📋 ИСТОРИЯ</h3>
    <div style="max-height:250px;overflow:auto"><table id="history_table"></table></div>
</div>

<div class="card">
    <h3>📡 ЛОГИ</h3>
    <div id="logs" class="log-panel">Загрузка...</div>
</div>

<div class="footer">
    ⚡ RSI+MACD+Bollinger | 🛡️ Стоп-лосс -3.5% | 🎯 Трейлинг-стоп +3%→-2% | 📊 300+ монет
</div>
</div>

<script>
function showBuy(){let c=prompt("Монета:","XTZUSDT"); if(c){let a=prompt("Сумма:","10"); if(a) fetch(`/cmd/buy?symbol=${c}&amount=${a}`);}}
function showSell(){let c=prompt("Монета:",""); if(c) fetch(`/cmd/sell?symbol=${c}`);}
function runBacktest(){let c=prompt("Монета для бэктеста:","BTCUSDT"); if(c) fetch(`/cmd/backtest?symbol=${c}`).then(r=>r.json()).then(d=>alert(`Результат: ${d.profit_pct}% за 30д, винрейт ${d.winrate}%`));}
function update(){fetch('/data').then(r=>r.json()).then(d=>{
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    document.getElementById('pos_count').innerHTML=d.positions.length;
    document.getElementById('total_trades').innerHTML=d.total_trades;
    document.getElementById('total_profit').innerHTML='$'+d.total_profit;
    document.getElementById('btc').innerHTML='$'+d.btc;
    document.getElementById('eth').innerHTML='$'+d.eth;
    document.getElementById('sol').innerHTML='$'+d.sol;
    let s='<thead><tr><th>Монета</th><th>Сигнал</th><th>%</th><th>RSI</th><th>MACD</th><th>BB</th></thead><tbody>';
    for(let sig of d.buy_signals.slice(0,15)){
        s+=`<tr><td><b>${sig.symbol}</b></td><td><span class="signal-buy">BUY</span></td><td>${sig.confidence}%</td><td>${sig.rsi}</td><td>${sig.macd>0?'📈':'📉'}</td><td>${sig.bb_pos<0.3?'📊':'🔴'}</td></tr>`;
    }
    s+='</tbody>';
    document.getElementById('signals_table').innerHTML=s;
    let p='<thead><tr><th>Монета</th><th>Прибыль</th><th>Вложено</th></thead><tbody>';
    for(let pos of d.positions){
        p+=`<tr><td>${pos.symbol}</td><td class="${pos.profit>=0?'profit':'loss'}">${pos.profit.toFixed(2)}%</td><td>$${pos.invested}</td></tr>`;
    }
    p+='</tbody>';
    document.getElementById('positions_table').innerHTML=p;
    let h='<thead><tr><th>Время</th><th>Монета</th><th>Тип</th><th>Прибыль</th></thead><tbody>';
    for(let ev of d.history.slice(0,20)){
        h+=`<tr><td>${ev.time}</td><td>${ev.symbol}</td><td>${ev.side}</td><td class="${ev.profit>=0?'profit':'loss'}">${ev.profit>0?'+':''}${ev.profit}</td></tr>`;
    }
    h+='</tbody>';
    document.getElementById('history_table').innerHTML=h;
    let l=''; for(let log of d.logs.slice(0,30)) l+=`<div>[${log.time}] ${log.msg}</div>`;
    document.getElementById('logs').innerHTML=l;
});}
setInterval(update,2500);update();
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def data():
    buy = [{"symbol":k,"confidence":v["confidence"],"rsi":v["rsi"],"price":v["price"],"macd":v.get("details",{}).get("macd",0),"bb_pos":v.get("details",{}).get("bb_pos",0.5)} 
           for k,v in signals.items() if v["signal"]=="BUY"]
    buy.sort(key=lambda x: x["confidence"], reverse=True)
    pos_data = []
    for p in positions:
        cur = get_price(p["symbol"])
        profit = (cur - p["entry_price"]) / p["entry_price"] * 100 if cur>0 else 0
        pos_data.append({"symbol":p["symbol"], "profit":profit, "invested":p["invested"]})
    total_profit = sum(p["invested"] * ((get_price(p["symbol"])-p["entry_price"])/p["entry_price"]) for p in positions if get_price(p["symbol"])>0)
    return jsonify({
        "balance":round(balance,2), "auto_pilot":auto_pilot,
        "buy_signals":buy[:50], "positions":pos_data,
        "total_trades":len(history), "total_profit":round(total_profit,2),
        "btc":get_price("BTCUSDT"), "eth":get_price("ETHUSDT"), "sol":get_price("SOLUSDT"),
        "history":history, "logs":logs
    })

@app.route('/cmd/auto')
def cmd_auto():
    global auto_pilot
    auto_pilot = not auto_pilot
    add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
    return "ok"

@app.route('/cmd/close')
def cmd_close():
    global balance, positions
    for p in positions[:]:
        if market_sell(p["symbol"], p["quantity"]):
            balance += p["invested"]
    positions.clear()
    add_log("🔒 Все позиции закрыты")
    return "ok"

@app.route('/cmd/buy')
def cmd_buy():
    global balance
    sym = request.args.get('symbol','')
    amt = float(request.args.get('amount',0))
    if sym and amt>0 and amt <= balance:
        price = get_price(sym)
        if price < 1:
            qty = int(amt / price)
            actual = qty * price
        else:
            qty = amt / price
            actual = amt
        if market_buy(sym, actual):
            balance -= actual
            positions.append({
                "symbol": sym, "entry_price": price, "invested": actual, "quantity": qty,
                "entry_time": time.time(), "peak_price": price, "peak_profit": 0, "confidence": 100
            })
            add_log(f"🟢 РУЧНАЯ ПОКУПКА {sym}: ${actual:.2f}")
    return "ok"

@app.route('/cmd/sell')
def cmd_sell():
    sym = request.args.get('symbol','')
    for p in positions[:]:
        if p["symbol"] == sym and market_sell(sym, p["quantity"]):
            global balance
            balance += p["invested"]
            positions.remove(p)
            add_log(f"🔴 ПРОДАЖА {sym}")
            break
    return "ok"

@app.route('/cmd/backtest')
def cmd_backtest():
    sym = request.args.get('symbol','BTCUSDT')
    result = backtest_strategy(sym, 30)
    return jsonify(result if result else {"error": "Нет данных"})

# ============================================================
# 9. ОСНОВНОЙ ЦИКЛ
# ============================================================

def main():
    global balance, running
    
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    balance = get_balance()
    
    print("\n" + "="*80)
    print("   🚀 ABSOLUTE ULTIMATE BOT FINAL - ИДЕАЛЬНАЯ ВЕРСИЯ")
    print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
    print("="*80)
    print(f"💰 Баланс: ${balance:.2f}")
    print(f"📡 Отслеживается монет: {len(COINS)}")
    print(f"📊 Индикаторы: RSI + MACD + Bollinger Bands")
    print(f"🌐 Веб-интерфейс: http://localhost:5002")
    print(f"🎮 КОМАНДЫ В КОНСОЛИ: A - Автопилот | C - Закрыть всё | Q - Выход")
    print("="*80)
    
    last_scan = 0
    last_daily = datetime.now().hour
    
    while running:
        try:
            balance = get_balance()
            
            if time.time() - last_scan >= SCAN_INTERVAL:
                for coin in COINS[:300]:
                    price = get_price(coin)
                    if price == 0: continue
                    signal, conf, rsi, details = analyze_full(coin, price)
                    signals[coin] = {"signal": signal, "confidence": conf, "price": price, "rsi": round(rsi,1), "details": details}
                auto_trade()
                last_scan = time.time()
            
            check_trailing_stop()
            
            if datetime.now().hour == 0 and last_daily != 0:
                daily_report()
                last_daily = 0
            elif datetime.now().hour != 0:
                last_daily = datetime.now().hour
            
            time.sleep(2)
            
        except KeyboardInterrupt:
            running = False
            print("\n🛑 Бот остановлен")
            break
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()