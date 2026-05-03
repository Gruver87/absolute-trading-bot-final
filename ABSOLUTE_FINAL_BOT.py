# -*- coding: utf-8 -*-
# ABSOLUTE_FINAL_BOT.py - ВСЯ ЛУЧШАЯ ФУНКЦИОНАЛЬНОСТЬ В ОДНОМ ФАЙЛЕ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import threading
import json
from datetime import datetime
from collections import defaultdict
from flask import Flask, jsonify, render_template_string

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

# ===== API КЛЮЧИ =====
MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

# ===== TELEGRAM =====
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ===== ТОРГУЕМЫЕ МОНЕТЫ =====
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# ===== ПАРАМЕТРЫ =====
TRADE_SIZE = 10
MAX_POSITIONS = 3
MIN_CONFIDENCE = 60
RSI_BUY = 35
RSI_SELL = 65
STOP_LOSS = 3.5
TAKE_PROFIT = 7.0
TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0

# ============================================================================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ============================================================================

balance = 0
positions = []
signals = {}
logs = []
auto_pilot = True
running = True

# ============================================================================
# БАЗОВЫЕ ФУНКЦИИ
# ============================================================================

def sign(params):
    return hmac.new(MEXC_API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_balance():
    """Получение баланса USDT с MEXC"""
    try:
        timestamp = int(time.time() * 1000)
        params = f"timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/account?{params}&signature={signature}"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            for b in r.json().get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except:
        pass
    return 0

def get_price(symbol):
    """Получение цены монеты"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(symbol, limit=50):
    """Получение исторических свечей"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except:
        pass
    return []

def market_buy(symbol, amount):
    """Реальная покупка"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        qty = round(amount / price, 6)
        if qty < 0.000001:
            return False
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except:
        return False

def market_sell(symbol, amount):
    """Реальная продажа"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        qty = round(amount / price, 6)
        if qty < 0.000001:
            return False
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={qty}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except:
        return False

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:300]}, timeout=3)
    except:
        pass

def add_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, {"time": timestamp, "msg": msg})
    if len(logs) > 100:
        logs.pop()
    print(f"[{timestamp}] {msg}")

# ============================================================================
# АНАЛИЗ (RSI + SMA + Моментум)
# ============================================================================

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze(symbol, price):
    """Анализ монеты - возвращает сигнал и уверенность"""
    prices = get_klines(symbol, 50)
    if len(prices) < 30:
        return "HOLD", 0, 50
    
    rsi = calculate_rsi(prices)
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    
    score = 0
    if rsi < RSI_BUY:
        score += 40
    elif rsi > RSI_SELL:
        score -= 40
    
    if sma5 > sma20:
        score += 20
    elif sma5 < sma20:
        score -= 20
    
    if len(prices) >= 10:
        mom = (prices[-1] - prices[-10]) / prices[-10] * 100
        if mom > 1:
            score += 15
        elif mom < -1:
            score -= 15
    
    if score > 25:
        return "BUY", min(90, 60 + score), rsi
    elif score < -25:
        return "SELL", min(90, 60 + abs(score)), rsi
    else:
        return "HOLD", 0, rsi

# ============================================================================
# ТОРГОВЛЯ
# ============================================================================

def get_position(symbol):
    for p in positions:
        if p["symbol"] == symbol:
            return p
    return None

def scan_market():
    """Сканирование рынка и автопилот"""
    global signals, balance
    
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        
        signal, confidence, rsi = analyze(coin, price)
        signals[coin] = {"signal": signal, "confidence": confidence, "price": price, "rsi": rsi}
        
        # Автопилот - покупка
        if auto_pilot and signal == "BUY" and confidence >= MIN_CONFIDENCE:
            if get_position(coin) is None and len(positions) < MAX_POSITIONS:
                if balance >= TRADE_SIZE:
                    if market_buy(coin, TRADE_SIZE):
                        balance -= TRADE_SIZE
                        positions.append({
                            "symbol": coin,
                            "entry_price": price,
                            "amount": TRADE_SIZE,
                            "confidence": confidence,
                            "entry_time": time.time(),
                            "peak_price": price,
                            "peak_profit": 0
                        })
                        add_log(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE} по ${price:.0f} ({confidence}%)")
                        send_telegram(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE}")

def check_positions():
    """Проверка позиций с трейлинг-стопом"""
    global balance, positions
    closed = []
    
    for pos in positions[:]:
        price = get_price(pos["symbol"])
        if price == 0:
            continue
        
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        pos["current_profit"] = profit
        
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        # Трейлинг-стоп
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            drop = pos["peak_profit"] - profit
            if drop >= TRAILING_DISTANCE:
                if market_sell(pos["symbol"], pos["amount"]):
                    balance += pos["amount"]
                    add_log(f"🎯 ТРЕЙЛИНГ-СТОП {pos['symbol']}: {profit:+.2f}% (пик: +{pos['peak_profit']:.1f}%)")
                    send_telegram(f"🎯 ПРОДАЖА {pos['symbol']}: {profit:+.2f}%")
                    closed.append(pos)
                continue
        
        # Тейк-профит
        if profit >= TAKE_PROFIT:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🎯 ТЕЙК-ПРОФИТ {pos['symbol']}: {profit:+.2f}%")
                send_telegram(f"🎉 ПРОДАЖА {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
        
        # Стоп-лосс
        if profit <= -STOP_LOSS:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🛑 СТОП-ЛОСС {pos['symbol']}: {profit:+.2f}%")
                send_telegram(f"📉 ПРОДАЖА {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
    
    for pos in closed:
        positions.remove(pos)

# ============================================================================
# ФУНКЦИЯ ДЛЯ КОМАНД
# ============================================================================

def input_handler():
    global auto_pilot, running
    while running:
        try:
            cmd = input().strip().lower()
            if cmd == 'a':
                auto_pilot = not auto_pilot
                add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
            elif cmd == 'c':
                for pos in positions[:]:
                    market_sell(pos["symbol"], pos["amount"])
                    balance += pos["amount"]
                positions = []
                add_log("🔒 Все позиции закрыты")
            elif cmd == 's':
                add_log(f"📊 Баланс: ${balance:.2f}, Позиций: {len(positions)}")
            elif cmd == 't':
                send_telegram(f"🤖 Бот работает! Баланс: ${balance:.2f}")
                add_log("📱 Telegram тест отправлен")
            elif cmd == 'q':
                running = False
                add_log("🛑 Бот остановлен")
                break
        except:
            pass
        time.sleep(0.1)

# ============================================================================
# FLASK ВЕБ-СЕРВЕР
# ============================================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>ABSOLUTE FINAL BOT</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
        table{width:100%}td,th{padding:5px;border-bottom:1px solid #333}
        .button{background:#0f0;color:#000;padding:8px 15px;margin:5px;border:none;border-radius:5px;cursor:pointer;font-weight:bold}
        .btn-danger{background:#f00;color:#fff}
    </style>
</head>
<body>
<h1>🤖 ABSOLUTE FINAL BOT</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
<p>⚡ Трейлинг-стоп: активация +3%, отступ 2% от максимума | Нет фиксированного тейк-профита!</p>

<div class="card">
    <h2>💰 ПОРТФЕЛЬ</h2>
    <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
    <div class="stat"><span>Автопилот:</span><span id="autopilot">ВКЛ</span></div>
    <div class="stat"><span>Позиций:</span><span id="positions_count">0</span></div>
</div>

<div class="card">
    <h2>🎯 СИГНАЛЫ</h2>
    <div id="signals">Загрузка...</div>
</div>

<div class="card">
    <h2>📈 ПОЗИЦИИ</h2>
    <div id="positions">Нет</div>
</div>

<div class="card">
    <h2>🎮 УПРАВЛЕНИЕ</h2>
    <button class="button" onclick="fetch('/cmd/auto')">🤖 АВТОПИЛОТ</button>
    <button class="button btn-danger" onclick="fetch('/cmd/close')">🔒 ЗАКРЫТЬ ВСЁ</button>
    <button class="button" onclick="fetch('/cmd/scan')">🔄 СКАНИРОВАТЬ</button>
    <button class="button" onclick="fetch('/cmd/tg')">📱 TELEGRAM</button>
</div>

<div class="card">
    <h2>📋 ЛОГИ</h2>
    <div id="logs" style="height:200px;overflow:auto;font-size:11px">Загрузка...</div>
</div>
</body>
<script>
async function update(){
    const r=await fetch('/data');
    const d=await r.json();
    document.getElementById('balance').innerHTML='$'+d.balance.toFixed(2);
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    document.getElementById('positions_count').innerHTML=d.positions.length;
    
    let s='<table><tr><th>Монета</th><th>Сигнал</th><th>%</th><th>RSI</th><th>Цена</th></tr>';
    for(let sig of d.signals){
        s+=`<tr><td><b>${sig.symbol}</b></td><td class="${sig.signal==='BUY'?'profit':'loss'}">${sig.signal}</td><td>${sig.confidence}%</td><td>${sig.rsi}</td><td>$${sig.price}</td></tr>`;
    }
    s+='</table>';
    document.getElementById('signals').innerHTML=s;
    
    let p='';
    for(let pos of d.positions){
        p+=`<div class="stat"><span>${pos.symbol}</span><span class="${pos.current_profit>=0?'profit':'loss'}">${pos.current_profit.toFixed(2)}%</span><span>$${pos.amount}</span></div>`;
    }
    document.getElementById('positions').innerHTML=p||'Нет позиций';
    
    let l='';
    for(let log of d.logs.slice(0,20)){
        l+=`<div>[${log.time}] ${log.msg}</div>`;
    }
    document.getElementById('logs').innerHTML=l;
}
setInterval(update,2000);
update();
</script>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/data')
def data():
    return jsonify({
        "balance": balance,
        "auto_pilot": auto_pilot,
        "signals": [{"symbol": k, **v} for k, v in signals.items()],
        "positions": positions,
        "logs": logs
    })

@app.route('/cmd/<cmd>')
def command(cmd):
    global auto_pilot, balance, positions
    if cmd == 'auto':
        auto_pilot = not auto_pilot
        add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
    elif cmd == 'close':
        for pos in positions[:]:
            market_sell(pos["symbol"], pos["amount"])
            balance += pos["amount"]
            positions.remove(pos)
        add_log("🔒 Все позиции закрыты")
    elif cmd == 'scan':
        scan_market()
        add_log("🔍 Сканирование выполнено")
    elif cmd == 'tg':
        send_telegram(f"🤖 БОТ АКТИВЕН\nБаланс: ${balance:.2f}\nПозиций: {len(positions)}")
        add_log("📱 Telegram отправлен")
    return "ok"

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def main():
    global balance, running
    
    # Запуск веб-сервера
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    web_thread.start()
    
    # Запуск обработчика команд
    cmd_thread = threading.Thread(target=input_handler, daemon=True)
    cmd_thread.start()
    
    # Получаем начальный баланс
    balance = get_balance()
    
    add_log("🚀 ABSOLUTE FINAL BOT v1.0 ЗАПУЩЕН")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log(f"📡 Отслеживается монет: {len(COINS)}")
    add_log("🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    add_log("🎮 КОМАНДЫ: A - Автопилот, C - Закрыть всё, S - Статус, T - Telegram, Q - Выход")
    
    send_telegram(f"🚀 БОТ ЗАПУЩЕН\n💰 Баланс: ${balance:.2f}")
    
    last_scan = 0
    
    while running:
        try:
            # Обновляем баланс
            balance = get_balance()
            
            # Сканируем рынок
            if time.time() - last_scan > 10:
                scan_market()
                last_scan = time.time()
            
            # Проверяем позиции
            check_positions()
            
            # Выводим дашборд
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\n" + "=" * 70)
            print("   🤖 ABSOLUTE FINAL BOT v1.0")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 70)
            print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   💰 БАЛАНС: ${balance:.2f}")
            print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
            print(f"   📊 ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
            print(f"\n   🎯 СИГНАЛЫ:")
            for coin, data in list(signals.items())[:8]:
                emoji = "📈" if data["signal"] == "BUY" else "📉" if data["signal"] == "SELL" else "⏸️"
                print(f"      {emoji} {coin}: {data['signal']} ({data['confidence']}%) | RSI={data['rsi']:.0f} | ${data['price']:.0f}")
            
            if positions:
                print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
                for pos in positions:
                    print(f"      📈 {pos['symbol']}: {pos['current_profit']:+.2f}% (пик: +{pos.get('peak_profit', 0):.1f}%)")
            
            print("\n" + "=" * 70)
            print("   🎮 КОМАНДЫ: A - Автопилот | C - Закрыть всё | S - Статус | T - Telegram | Q - Выход")
            print("   🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
            print("=" * 70)
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            add_log("🛑 Бот остановлен")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()