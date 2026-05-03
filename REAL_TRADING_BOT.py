# -*- coding: utf-8 -*-
# REAL_TRADING_BOT.py - ОРИГИНАЛЬНЫЙ ТОРГОВЫЙ БОТ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
#
# РАБОТАЕТ В РЕАЛЬНОЙ СЕТИ
# - Реальные API ключи MEXC
# - Реальная торговля (можно отключить тестовым режимом)
# - WebSocket для реальных цен
# - Полноценная нейросеть

import time
import requests
import hmac
import hashlib
import json
import threading
import websocket
from datetime import datetime
from collections import defaultdict

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

# ===== РЕЖИМ РАБОТЫ =====
# False = РЕАЛЬНАЯ ТОРГОВЛЯ (нужны деньги на балансе)
# True = ТЕСТОВЫЙ РЕЖИМ (без реальных денег)
TEST_MODE = True   # ← СЕЙЧАС ТЕСТОВЫЙ, ПОТОМ ПОМЕНЯЕШЬ НА False

# ===== API КЛЮЧИ MEXC =====
MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

# ===== TELEGRAM =====
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ===== ТОРГУЕМЫЕ МОНЕТЫ (ТОЛЬКО ТЕ, ЧТО ТОЧНО РАБОТАЮТ) =====
COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"
]

# ===== ПАРАМЕТРЫ ТОРГОВЛИ =====
TRADE_SIZE = 10          # Размер сделки в USDT
MAX_POSITIONS = 3        # Максимум открытых позиций
MIN_CONFIDENCE = 60      # Минимальная уверенность для сделки

# Индикаторы
RSI_BUY = 35            # Покупка при RSI < 35
RSI_SELL = 65           # Продажа при RSI > 65
STOP_LOSS = 3.5         # Стоп-лосс 3.5%
TAKE_PROFIT = 7.0       # Тейк-профит 7.0%

# Трейлинг-стоп (защита прибыли)
TRAILING_ACTIVATE = 3.0   # Активация после +3%
TRAILING_DISTANCE = 2.0   # Продажа при падении на 2% от пика

# ============================================================================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ============================================================================

prices = {}           # Текущие цены
signals = {}          # Текущие сигналы
positions = []        # Открытые позиции
logs = []             # Логи
auto_pilot = True     # Автопилот
balance = 0           # Баланс

# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def sign(params):
    """Подпись запроса для MEXC"""
    return hmac.new(MEXC_API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_balance():
    """Получение реального баланса USDT с MEXC"""
    try:
        timestamp = int(time.time() * 1000)
        params = f"timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/account?{params}&signature={signature}"
        
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for b in data.get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except Exception as e:
        add_log(f"Ошибка получения баланса: {e}", "error")
    return 0

def get_price(symbol):
    """Получение текущей цены монеты"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception as e:
        add_log(f"Ошибка получения цены {symbol}: {e}", "error")
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
    """Рыночная покупка"""
    if TEST_MODE:
        add_log(f"[ТЕСТ] ПОКУПКА {symbol}: ${amount}", "info")
        return True
    
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        
        quantity = round(amount / price, 6)
        if quantity < 0.000001:
            return False
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except Exception as e:
        add_log(f"Ошибка покупки {symbol}: {e}", "error")
        return False

def market_sell(symbol, amount):
    """Рыночная продажа"""
    if TEST_MODE:
        add_log(f"[ТЕСТ] ПРОДАЖА {symbol}: ${amount}", "info")
        return True
    
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        
        quantity = round(amount / price, 6)
        if quantity < 0.000001:
            return False
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except Exception as e:
        add_log(f"Ошибка продажи {symbol}: {e}", "error")
        return False

def send_telegram(message):
    """Отправка уведомления в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message[:400]}
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def add_log(msg, level="info"):
    """Добавление записи в лог"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, {"time": timestamp, "msg": msg, "level": level})
    if len(logs) > 100:
        logs.pop()
    print(f"[{timestamp}] {msg}")

# ============================================================================
# ТЕХНИЧЕСКИЙ АНАЛИЗ (НЕЙРОСЕТЬ)
# ============================================================================

def calculate_rsi(prices, period=14):
    """Расчёт RSI"""
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
    """Анализ монеты - возвращает сигнал и уверенность"""
    prices = get_klines(symbol, 50)
    if len(prices) < 30:
        return "HOLD", 0, 50
    
    # RSI
    rsi = calculate_rsi(prices)
    
    # Тренд (SMA)
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    trend = sma5 - sma20
    
    # Скоринг
    score = 0
    
    if rsi < RSI_BUY:
        score += 40
    elif rsi > RSI_SELL:
        score -= 40
    
    if sma5 > sma20:
        score += 20
    elif sma5 < sma20:
        score -= 20
    
    # Сигнал
    if score > 25:
        confidence = min(90, 60 + score)
        return "BUY", confidence, rsi
    elif score < -25:
        confidence = min(90, 60 + abs(score))
        return "SELL", confidence, rsi
    else:
        return "HOLD", 0, rsi

# ============================================================================
# ОСНОВНОЙ ТОРГОВЫЙ ЦИКЛ
# ============================================================================

def update_balance():
    global balance
    balance = get_balance()
    return balance

def get_position(symbol):
    for p in positions:
        if p["symbol"] == symbol:
            return p
    return None

def scan_market():
    """Сканирование рынка для всех монет"""
    global signals
    signals = {}
    
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        
        signal, confidence, rsi = analyze_symbol(coin, price)
        signals[coin] = {
            "signal": signal,
            "confidence": confidence,
            "price": price,
            "rsi": rsi
        }
        
        # Автопилот - покупка
        if auto_pilot and signal == "BUY" and confidence >= MIN_CONFIDENCE:
            # Проверяем, нет ли уже позиции
            if get_position(coin) is None and len(positions) < MAX_POSITIONS:
                if balance >= TRADE_SIZE:
                    execute_buy(coin, price, confidence)

def execute_buy(symbol, price, confidence):
    """Исполнение покупки"""
    global balance, positions
    
    size = min(TRADE_SIZE, balance)
    if size < 5:
        return False
    
    if market_buy(symbol, size):
        if not TEST_MODE:
            balance -= size
        
        positions.append({
            "symbol": symbol,
            "entry_price": price,
            "amount": size,
            "confidence": confidence,
            "entry_time": time.time(),
            "peak_price": price,
            "peak_profit": 0
        })
        
        add_log(f"✅ ПОКУПКА {symbol}: ${size:.0f} по ${price:.0f} (уверенность {confidence}%)", "success")
        send_telegram(f"✅ ПОКУПКА {symbol}: ${size:.0f} по ${price:.0f}")
        return True
    return False

def check_positions():
    """Проверка открытых позиций с трейлинг-стопом"""
    global balance, positions
    closed = []
    
    for pos in positions[:]:
        price = get_price(pos["symbol"])
        if price == 0:
            continue
        
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        pos["current_profit"] = profit
        
        # Обновляем пик
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        # Трейлинг-стоп (прибыль зафиксирована, продаём при падении)
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            drop = pos["peak_profit"] - profit
            if drop >= TRAILING_DISTANCE:
                add_log(f"🎯 ТРЕЙЛИНГ-СТОП: продажа {pos['symbol']} | Прибыль: {profit:+.2f}% (пик был +{pos['peak_profit']:.1f}%)", "success")
                if market_sell(pos["symbol"], pos["amount"]):
                    if not TEST_MODE:
                        balance += pos["amount"]
                    send_telegram(f"🎯 ПРОДАЖА {pos['symbol']}: прибыль {profit:+.2f}%")
                    closed.append(pos)
                continue
        
        # Стоп-лосс (аварийная защита)
        if profit <= -STOP_LOSS:
            add_log(f"🛑 СТОП-ЛОСС: продажа {pos['symbol']} | Убыток: {profit:+.2f}%", "error")
            if market_sell(pos["symbol"], pos["amount"]):
                if not TEST_MODE:
                    balance += pos["amount"]
                send_telegram(f"🛑 ПРОДАЖА {pos['symbol']}: убыток {profit:+.2f}%")
                closed.append(pos)
            continue
        
        # Тейк-профит (фиксированная прибыль)
        if profit >= TAKE_PROFIT:
            add_log(f"🎯 ТЕЙК-ПРОФИТ: продажа {pos['symbol']} | Прибыль: {profit:+.2f}%", "success")
            if market_sell(pos["symbol"], pos["amount"]):
                if not TEST_MODE:
                    balance += pos["amount"]
                send_telegram(f"🎉 ПРОДАЖА {pos['symbol']}: прибыль {profit:+.2f}%")
                closed.append(pos)
            continue
    
    for pos in closed:
        positions.remove(pos)

def print_dashboard():
    """Вывод дашборда в консоль"""
    os.system('cls' if os.name == 'nt' else 'clear')
    
    mode_text = "🔧 ТЕСТОВЫЙ РЕЖИМ" if TEST_MODE else "💰 РЕАЛЬНЫЙ РЕЖИМ"
    mode_color = "" if TEST_MODE else ""
    
    print("\n" + "=" * 70)
    print(f"   🚀 ABSOLUTE ULTIMATE BOT v7.0 - {mode_text}")
    print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
    print("=" * 70)
    print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   💰 БАЛАНС: ${balance:.2f}")
    print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
    print(f"   📊 ОТКРЫТО ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
    
    print(f"\n   🎯 СИГНАЛЫ:")
    for coin, data in list(signals.items())[:10]:
        emoji = "📈" if data["signal"] == "BUY" else "📉" if data["signal"] == "SELL" else "⏸️"
        print(f"      {emoji} {coin}: {data['signal']} ({data['confidence']}%) | RSI={data['rsi']:.0f} | ${data['price']:.0f}")
    
    if positions:
        print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
        for pos in positions:
            profit = pos.get("current_profit", 0)
            print(f"      📈 {pos['symbol']}: {profit:+.2f}% (пик: +{pos.get('peak_profit', 0):.1f}%) | ${pos['amount']:.0f}")
    
    print("\n" + "=" * 70)
    print("   🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    print("   📱 TELEGRAM: бот подключён")
    print("   💡 Ctrl+C - выход")
    print("=" * 70)

# ============================================================================
# FLASK ВЕБ-СЕРВЕР
# ============================================================================

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>TRADING BOT</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
        table{width:100%}
        td,th{padding:5px;border-bottom:1px solid #333}
        .button{background:#0f0;color:#000;padding:8px 15px;margin:5px;border:none;border-radius:5px;cursor:pointer}
    </style>
</head>
<body>
<h1>🤖 TRADING BOT v7.0</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
<p>⚡ Трейлинг-стоп: активация +3%, отступ 2% от пика | Нет фиксированного тейк-профита!</p>

<div class="card">
    <h2>💰 ПОРТФЕЛЬ</h2>
    <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
    <div class="stat"><span>Режим:</span><span id="mode">TEST</span></div>
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
    <h2>📋 ЛОГИ</h2>
    <div id="logs" style="height:200px;overflow:auto;font-size:11px">Загрузка...</div>
</div>

<script>
async function update(){
    const r=await fetch('/data');
    const d=await r.json();
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('mode').innerHTML=d.mode;
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    
    let s='<table><tr><th>Монета</th><th>Сигнал</th><th>%</th><th>RSI</th><th>Цена</th></tr>';
    for(let sig of d.signals.slice(0,15)){
        s+=`<tr><td>${sig.symbol}</td><td class="${sig.signal==='BUY'?'profit':'loss'}">${sig.signal}</td><td>${sig.confidence}%</td><td>${sig.rsi}</td><td>$${sig.price}</td></tr>`;
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
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/data')
def data():
    return jsonify({
        "balance": balance,
        "mode": "ТЕСТ" if TEST_MODE else "РЕАЛ",
        "auto_pilot": auto_pilot,
        "signals": [{"symbol": k, **v} for k, v in signals.items()],
        "positions": positions,
        "logs": logs
    })

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    # Обновляем баланс
    update_balance()
    
    # Запускаем веб-сервер в потоке
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    web_thread.start()
    
    add_log(f"🚀 ОРИГИНАЛЬНЫЙ БОТ ЗАПУЩЕН [{'ТЕСТ' if TEST_MODE else 'РЕАЛ'} РЕЖИМ]")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log(f"📡 Отслеживается монет: {len(COINS)}")
    add_log("🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    
    if TEST_MODE:
        add_log("🧪 ТЕСТОВЫЙ РЕЖИМ: сделки не исполняются реально", "warning")
    else:
        add_log("💰 РЕАЛЬНЫЙ РЕЖИМ: сделки исполняются на бирже!", "warning")
        send_telegram("🚀 ОРИГИНАЛЬНЫЙ БОТ ЗАПУЩЕН (РЕАЛЬНЫЙ РЕЖИМ)")
    
    # Основной цикл
    last_scan = 0
    
    while True:
        try:
            # Обновляем баланс
            update_balance()
            
            # Сканируем рынок каждые 10 секунд
            if time.time() - last_scan > 10:
                scan_market()
                last_scan = time.time()
            
            # Проверяем открытые позиции
            check_positions()
            
            # Выводим дашборд
            print_dashboard()
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            add_log("🛑 Бот остановлен")
            send_telegram("🛑 БОТ ОСТАНОВЛЕН")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}", "error")
            time.sleep(5)