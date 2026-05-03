# -*- coding: utf-8 -*-
# ULTIMATE_WORKING_BOT_FIXED.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

# ============================================================================
# КЛЮЧИ
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# ТОРГУЕМЫЕ МОНЕТЫ
# ============================================================================

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

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
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================================================

balance = 0
positions = []
signals = {}
logs = []
auto_pilot = True
running = True

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def sign(params):
    return hmac.new(MEXC_API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_balance():
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
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(symbol, limit=50):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except:
        pass
    return []

def market_buy(symbol, amount):
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
# АНАЛИЗ
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

def analyze_symbol(symbol, price):
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
    
    if score > 25:
        confidence = min(90, 60 + score)
        return "BUY", confidence, rsi
    elif score < -25:
        confidence = min(90, 60 + abs(score))
        return "SELL", confidence, rsi
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
    global signals, balance
    
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        
        signal, confidence, rsi = analyze_symbol(coin, price)
        signals[coin] = {
            "signal": signal,
            "confidence": confidence,
            "price": price,
            "rsi": round(rsi, 1)
        }
        
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
                        add_log(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE} по ${price:.0f}")
                        send_telegram(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE}")

def check_positions():
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
        
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            drop = pos["peak_profit"] - profit
            if drop >= TRAILING_DISTANCE:
                if market_sell(pos["symbol"], pos["amount"]):
                    balance += pos["amount"]
                    add_log(f"🎯 ТРЕЙЛИНГ-СТОП {pos['symbol']}: {profit:+.2f}%")
                    closed.append(pos)
                continue
        
        if profit >= TAKE_PROFIT:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🎉 ТЕЙК-ПРОФИТ {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
        
        if profit <= -STOP_LOSS:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🛑 СТОП-ЛОСС {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
    
    for pos in closed:
        positions.remove(pos)

# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>ULTIMATE WORKING BOT</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
        .button{background:#0f0;color:#000;padding:8px 15px;margin:5px;cursor:pointer;border-radius:5px}
        .btn-danger{background:#f00;color:#fff}
    </style>
</head>
<body>
<h1>🤖 ULTIMATE WORKING BOT</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>

<div class="card">
    <h2>💰 ПОРТФЕЛЬ</h2>
    <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
    <div class="stat"><span>Автопилот:</span><span id="autopilot">ВКЛ</span></div>
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
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    
    let s='';
    for(let sig of d.signals){
        s+=`<div class="stat"><span>${sig.symbol}</span><span class="${sig.signal==='BUY'?'profit':'loss'}">${sig.signal}</span><span>${sig.confidence}%</span><span>RSI=${sig.rsi}</span><span>$${sig.price}</span></div>`;
    }
    document.getElementById('signals').innerHTML=s||'Нет сигналов';
    
    let p='';
    for(let pos of d.positions){
        p+=`<div class="stat"><span>${pos.symbol}</span><span>${pos.current_profit?.toFixed(2)||0}%</span><span>$${pos.amount}</span></div>`;
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
        "balance": round(balance, 2),
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
            positions.clear()
        add_log("🔒 Все позиции закрыты")
    elif cmd == 'tg':
        send_telegram(f"🤖 БОТ АКТИВЕН\nБаланс: ${balance:.2f}")
        add_log("📱 Telegram отправлен")
    return "ok"

# ============================================================================
# КОНСОЛЬНЫЕ КОМАНДЫ
# ============================================================================

def console_handler():
    global auto_pilot, running, balance, positions
    
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
                    positions.clear()
                add_log("🔒 Все позиции закрыты")
            elif cmd == 's':
                add_log(f"📊 Баланс: ${balance:.2f}, Позиций: {len(positions)}")
            elif cmd == 't':
                send_telegram(f"📊 Статус: ${balance:.2f}")
                add_log("📱 Telegram отправлен")
            elif cmd == 'q':
                global running
                running = False
                add_log("🛑 Бот остановлен")
                break
        except:
            pass
        time.sleep(0.1)

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def main():
    global balance, running
    
    # Запуск веб-сервера
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    web_thread.start()
    
    # Запуск обработчика команд
    cmd_thread = threading.Thread(target=console_handler, daemon=True)
    cmd_thread.start()
    
    # Инициализация
    balance = get_balance()
    
    add_log("🚀 ULTIMATE WORKING BOT ЗАПУЩЕН")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log(f"📡 Монет: {len(COINS)}")
    add_log(f"🌐 http://localhost:5002")
    add_log(f"🎮 КОМАНДЫ: A - Автопилот | C - Закрыть | S - Статус | T - Telegram | Q - Выход")
    
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
            
            # Очистка экрана и вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\n" + "=" * 70)
            print("   🤖 ULTIMATE WORKING BOT")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 70)
            print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   💰 БАЛАНС: ${balance:.2f}")
            print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
            print(f"   📊 ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
            
            print(f"\n   🎯 СИГНАЛЫ:")
            for coin, data in signals.items():
                emoji = "📈" if data["signal"] == "BUY" else "📉" if data["signal"] == "SELL" else "⏸️"
                print(f"      {emoji} {coin}: {data['signal']} ({data['confidence']}%) | RSI={data['rsi']} | ${data['price']:.0f}")
            
            if positions:
                print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
                for pos in positions:
                    print(f"      📈 {pos['symbol']}: {pos['current_profit']:+.2f}%")
            
            print("\n" + "=" * 70)
            print("   🎮 A - Автопилот | C - Закрыть | S - Статус | T - Telegram | Q - Выход")
            print("   🌐 http://localhost:5002")
            print("=" * 70)
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            add_log("🛑 Бот остановлен пользователем")
            send_telegram("🛑 БОТ ОСТАНОВЛЕН")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()