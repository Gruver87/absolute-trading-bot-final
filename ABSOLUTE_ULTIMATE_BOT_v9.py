# -*- coding: utf-8 -*-
# ABSOLUTE_ULTIMATE_BOT_v9.py - ПОЛНАЯ РАБОЧАЯ ВЕРСИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
#
# ВКЛЮЧАЕТ ВСЕ ФУНКЦИИ:
# ✅ 49 монет
# ✅ RSI анализ
# ✅ Трейлинг-стоп
# ✅ Веб-дашборд
# ✅ Telegram уведомления
# ✅ Консольные команды
# ✅ Принудительные покупки
# ✅ Защита капитала

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# 49 МОНЕТ
# ============================================================================

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT",
    "ATOMUSDT", "LTCUSDT", "ETCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "FILUSDT", "SUIUSDT", "SEIUSDT", "TRXUSDT", "XLMUSDT",
    "VETUSDT", "HBARUSDT", "ICPUSDT", "EGLDUSDT", "THETAUSDT", "SANDUSDT",
    "MANAUSDT", "GALAUSDT", "AXSUSDT", "RNDRUSDT", "IMXUSDT", "STXUSDT",
    "MKRUSDT", "CRVUSDT", "SNXUSDT", "COMPUSDT", "ZECUSDT", "DASHUSDT",
    "XMRUSDT", "EOSUSDT", "XTZUSDT", "KSMUSDT", "WAVESUSDT", "ALGOUSDT", "FLOWUSDT"
]

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

TRADE_SIZE = 5
MAX_POSITIONS = 5
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
# ФУНКЦИИ API
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
        qty = round(amount / price, 8)
        if qty < 0.00000001:
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
        qty = round(amount / price, 8)
        if qty < 0.00000001:
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
    
    if rsi < RSI_BUY:
        confidence = min(90, 70 + (RSI_BUY - rsi))
        return "BUY", confidence, rsi
    elif rsi > RSI_SELL:
        confidence = min(90, 70 + (rsi - RSI_SELL))
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
                        add_log(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE} по ${price:.4f} (RSI={rsi:.0f})")
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
        
        # Трейлинг-стоп
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            drop = pos["peak_profit"] - profit
            if drop >= TRAILING_DISTANCE:
                if market_sell(pos["symbol"], pos["amount"]):
                    balance += pos["amount"]
                    add_log(f"🎯 ТРЕЙЛИНГ-СТОП {pos['symbol']}: {profit:+.2f}%")
                    closed.append(pos)
                continue
        
        # Тейк-профит
        if profit >= TAKE_PROFIT:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🎉 ТЕЙК-ПРОФИТ {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
        
        # Стоп-лосс
        if profit <= -STOP_LOSS:
            if market_sell(pos["symbol"], pos["amount"]):
                balance += pos["amount"]
                add_log(f"🛑 СТОП-ЛОСС {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
            continue
    
    for pos in closed:
        positions.remove(pos)

def force_buy(symbol):
    """Принудительная покупка монеты"""
    global balance, positions
    
    price = get_price(symbol)
    if price == 0:
        add_log(f"❌ Не удалось получить цену {symbol}")
        return False
    
    if get_position(symbol):
        add_log(f"⚠️ Позиция по {symbol} уже открыта")
        return False
    
    if balance < TRADE_SIZE:
        add_log(f"❌ Недостаточно средств: нужно ${TRADE_SIZE}, есть ${balance:.2f}")
        return False
    
    if market_buy(symbol, TRADE_SIZE):
        balance -= TRADE_SIZE
        positions.append({
            "symbol": symbol,
            "entry_price": price,
            "amount": TRADE_SIZE,
            "confidence": 100,
            "entry_time": time.time(),
            "peak_price": price,
            "peak_profit": 0
        })
        add_log(f"🔨 ПРИНУДИТЕЛЬНАЯ ПОКУПКА {symbol}: ${TRADE_SIZE} по {price:.6f}")
        send_telegram(f"🔨 ПОКУПКА {symbol}: ${TRADE_SIZE}")
        return True
    return False

# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ABSOLUTE ULTIMATE BOT v9.0</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #0d1a0d 50%, #0a0a0a 100%);
            font-family: 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            text-align: center;
            padding: 20px;
            border-bottom: 2px solid #0f0;
            margin-bottom: 20px;
        }
        .header h1 { font-size: 1.8em; text-shadow: 0 0 10px #0f0; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: rgba(0,0,0,0.75);
            backdrop-filter: blur(10px);
            border: 1px solid #0f0;
            border-radius: 15px;
            padding: 20px;
        }
        .card h3 {
            margin-bottom: 15px;
            border-left: 3px solid #0f0;
            padding-left: 12px;
        }
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #333;
        }
        .big-number {
            font-size: 2em;
            font-weight: bold;
            text-align: center;
            margin: 15px 0;
        }
        .signal-buy { color: #0f0; font-weight: bold; }
        .signal-sell { color: #f00; font-weight: bold; }
        .button {
            background: #0f0;
            color: #000;
            border: none;
            padding: 10px 20px;
            margin: 5px;
            cursor: pointer;
            font-weight: bold;
            border-radius: 8px;
            transition: all 0.2s;
        }
        .button:hover {
            transform: scale(1.02);
            box-shadow: 0 0 15px #0f0;
        }
        .btn-danger { background: #f00; color: #fff; }
        .btn-danger:hover { box-shadow: 0 0 15px #f00; }
        .btn-warning { background: #ff0; color: #000; }
        .button-group { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 15px; }
        .log-panel {
            background: #000;
            height: 200px;
            overflow-y: auto;
            font-size: 11px;
            padding: 12px;
            border-radius: 8px;
        }
        table { width: 100%; font-size: 12px; border-collapse: collapse; }
        th, td { padding: 8px 5px; text-align: left; border-bottom: 1px solid #333; }
        th { color: #0f0; border-bottom: 2px solid #0f0; }
        .footer {
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            color: #666;
            font-size: 11px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🤖 ABSOLUTE ULTIMATE BOT v9.0</h1>
        <p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
        <p>⚡ 49 монет | RSI анализ | Трейлинг-стоп | Telegram</p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>💰 ПОРТФЕЛЬ</h3>
            <div class="big-number" id="balance">$0.00</div>
            <div class="stat"><span>Автопилот:</span><span id="autopilot">✅ ВКЛ</span></div>
            <div class="stat"><span>Позиций:</span><span id="pos_count">0/5</span></div>
        </div>

        <div class="card">
            <h3>🎯 BUY СИГНАЛЫ (RSI &lt; 35)</h3>
            <div id="buy_signals" style="max-height: 300px; overflow-y: auto;">
                <div class="stat">Загрузка...</div>
            </div>
        </div>

        <div class="card">
            <h3>🎮 УПРАВЛЕНИЕ</h3>
            <div class="button-group">
                <button class="button btn-warning" onclick="fetch('/cmd/auto')">🤖 АВТОПИЛОТ</button>
                <button class="button btn-danger" onclick="fetch('/cmd/close')">🔒 ЗАКРЫТЬ ВСЁ</button>
                <button class="button" onclick="fetch('/cmd/buy_gala')">🟢 КУПИТЬ GALA</button>
                <button class="button" onclick="fetch('/cmd/buy_opusdt')">🟢 КУПИТЬ OPUSDT</button>
                <button class="button" onclick="fetch('/cmd/tg')">📱 TELEGRAM</button>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>📈 ОТКРЫТЫЕ ПОЗИЦИИ</h3>
        <div id="positions">Нет открытых позиций</div>
    </div>

    <div class="card">
        <h3>📋 LIVE ЛОГИ</h3>
        <div id="logs" class="log-panel">Загрузка...</div>
    </div>

    <div class="footer">
        <p>📊 Анализ: RSI | 🛡️ Стоп-лосс: 3.5% | 🎯 Трейлинг-стоп: активация +3%, отступ 2%</p>
    </div>
</div>

<script>
    async function update() {
        try {
            const r = await fetch('/data');
            const d = await r.json();
            
            document.getElementById('balance').innerHTML = `$${d.balance.toFixed(2)}`;
            document.getElementById('autopilot').innerHTML = d.auto_pilot ? '✅ ВКЛ' : '❌ ВЫКЛ';
            document.getElementById('pos_count').innerHTML = `${d.positions.length}/5`;
            
            let s = '';
            for (let sig of d.buy_signals.slice(0, 15)) {
                s += `<div class="stat">
                    <span><b>${sig.symbol}</b></span>
                    <span class="signal-buy">BUY</span>
                    <span>${sig.confidence}%</span>
                    <span>RSI=${sig.rsi}</span>
                    <span>$${sig.price}</span>
                </div>`;
            }
            document.getElementById('buy_signals').innerHTML = s || '<div class="stat">Нет сигналов BUY</div>';
            
            let p = '';
            for (let pos of d.positions) {
                p += `<div class="stat">
                    <span><b>${pos.symbol}</b></span>
                    <span class="${pos.current_profit >= 0 ? 'signal-buy' : 'signal-sell'}">${pos.current_profit?.toFixed(2) || 0}%</span>
                    <span>$${pos.amount}</span>
                </div>`;
            }
            document.getElementById('positions').innerHTML = p || '<div class="stat">Нет открытых позиций</div>';
            
            let l = '';
            for (let log of d.logs.slice(0, 25)) {
                l += `<div class="stat">[${log.time}] ${log.msg}</div>`;
            }
            document.getElementById('logs').innerHTML = l;
        } catch(e) { console.error(e); }
    }
    
    setInterval(update, 3000);
    update();
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def data():
    buy_signals = [{"symbol": k, **v} for k, v in signals.items() if v["signal"] == "BUY"]
    buy_signals.sort(key=lambda x: x["confidence"], reverse=True)
    return jsonify({
        "balance": round(balance, 2),
        "auto_pilot": auto_pilot,
        "buy_signals": buy_signals[:30],
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
    elif cmd == 'buy_gala':
        force_buy("GALAUSDT")
    elif cmd == 'buy_opusdt':
        force_buy("OPUSDT")
    elif cmd == 'tg':
        send_telegram(f"🤖 БОТ АКТИВЕН\nБаланс: ${balance:.2f}\nПозиций: {len(positions)}")
        add_log("📱 Telegram отправлен")
    return "ok"

# ============================================================================
# КОНСОЛЬНЫЙ ОБРАБОТЧИК
# ============================================================================

def console_handler():
    global auto_pilot, balance, positions, running
    
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
            elif cmd == 'g':
                force_buy("GALAUSDT")
            elif cmd == 'o':
                force_buy("OPUSDT")
            elif cmd == 's':
                add_log(f"📊 Статус: Баланс ${balance:.2f}, Позиций: {len(positions)}")
            elif cmd == 't':
                send_telegram(f"📊 Статус: Баланс ${balance:.2f}, Позиций: {len(positions)}")
                add_log("📱 Telegram отправлен")
            elif cmd == 'q':
                running = False
                add_log("🛑 Бот остановлен")
                send_telegram("🛑 Бот остановлен")
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
    
    add_log("🚀 ABSOLUTE ULTIMATE BOT v9.0 ЗАПУЩЕН")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log(f"📡 Монет: {len(COINS)}")
    add_log(f"🌐 Веб-интерфейс: http://localhost:5002")
    add_log(f"🎮 Команды: A - Автопилот | C - Закрыть всё | G - Купить GALA | O - Купить OPUSDT | S - Статус | T - Telegram | Q - Выход")
    
    send_telegram(f"🚀 БОТ ЗАПУЩЕН\n💰 Баланс: ${balance:.2f}\n📡 Монет: {len(COINS)}")
    
    last_scan = 0
    
    while running:
        try:
            balance = get_balance()
            
            if time.time() - last_scan > 10:
                scan_market()
                last_scan = time.time()
            
            check_positions()
            
            # Очистка экрана и вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            buy_signals = [(coin, data) for coin, data in signals.items() if data["signal"] == "BUY"]
            buy_signals.sort(key=lambda x: x[1]["confidence"], reverse=True)
            
            print("\n" + "=" * 80)
            print("   🤖 ABSOLUTE ULTIMATE BOT v9.0")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 80)
            print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   💰 БАЛАНС: ${balance:.2f}")
            print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
            print(f"   📊 ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
            print(f"   📡 МОНЕТ: {len(COINS)}")
            
            print(f"\n   🟢 BUY СИГНАЛЫ (RSI < {RSI_BUY}):")
            for coin, data in buy_signals[:15]:
                print(f"      📈 {coin}: {data['confidence']:.0f}% | RSI={data['rsi']} | ${data['price']:.6f}")
            
            if not buy_signals:
                print(f"      ⏸️ Нет сигналов BUY")
            
            if positions:
                print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
                for pos in positions:
                    print(f"      📈 {pos['symbol']}: {pos['current_profit']:+.2f}% | вход ${pos['entry_price']:.6f}")
            
            print("\n" + "=" * 80)
            print("   🎮 КОМАНДЫ: A - Автопилот | C - Закрыть | G - Купить GALA | O - Купить OPUSDT")
            print("   🎮 S - Статус | T - Telegram | Q - Выход")
            print("   🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
            print("=" * 80)
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            add_log("🛑 Бот остановлен пользователем")
            send_telegram("🛑 Бот остановлен")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()