# -*- coding: utf-8 -*-
# AUTO_TRADING_BOT.py - ПОЛНОСТЬЮ АВТОМАТИЧЕСКИЙ БОТ

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

# ============================================================================
# API КЛЮЧИ
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
MAX_POSITIONS = 3
RSI_BUY = 35
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

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_balance():
    try:
        t = int(time.time() * 1000)
        r = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sign(f'timestamp={t}')}", 
                        headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            for b in r.json().get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except:
        pass
    return 0

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(s, limit=50):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={s}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except:
        pass
    return []

def market_buy(s, a):
    try:
        p = get_price(s)
        if p == 0:
            return False
        qty = int(a / p)  # Целое количество
        if qty < 1:
            return False
        t = int(time.time() * 1000)
        params = f"symbol={s}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sign(params)}", 
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except:
        return False

def market_sell(s, a):
    try:
        p = get_price(s)
        if p == 0:
            return False
        qty = int(a / p)
        if qty < 1:
            return False
        t = int(time.time() * 1000)
        params = f"symbol={s}&side=SELL&type=MARKET&quantity={qty}&timestamp={t}"
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sign(params)}", 
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except:
        return False

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:300]}, timeout=3)
    except:
        pass

def add_log(msg):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(logs) > 100:
        logs.pop()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    ag = sum(gains) / period if gains else 0
    al = sum(losses) / period if losses else 0.001
    return 100 - (100 / (1 + ag / al))

def analyze(s, p):
    prices = get_klines(s, 50)
    if len(prices) < 30:
        return "HOLD", 0, 50
    rsi = calc_rsi(prices)
    if rsi < RSI_BUY:
        conf = min(90, 70 + (RSI_BUY - rsi))
        return "BUY", conf, rsi
    return "HOLD", 0, rsi

def scan_and_trade():
    global signals, balance, positions
    
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        
        signal, confidence, rsi = analyze(coin, price)
        signals[coin] = {"signal": signal, "confidence": confidence, "price": price, "rsi": round(rsi, 1)}
        
        # АВТОМАТИЧЕСКАЯ ПОКУПКА
        if auto_pilot and signal == "BUY" and len(positions) < MAX_POSITIONS:
            # Проверяем, нет ли уже позиции
            already_have = False
            for p in positions:
                if p["symbol"] == coin:
                    already_have = True
                    break
            if not already_have and balance >= TRADE_SIZE:
                if market_buy(coin, TRADE_SIZE):
                    balance -= TRADE_SIZE
                    positions.append({
                        "symbol": coin,
                        "entry_price": price,
                        "amount": TRADE_SIZE,
                        "entry_time": time.time(),
                        "peak_price": price,
                        "peak_profit": 0
                    })
                    add_log(f"✅ АВТОПОКУПКА {coin}: ${TRADE_SIZE} по {price:.6f} (RSI={rsi:.0f})")
                    send_telegram(f"✅ ПОКУПКА {coin}: ${TRADE_SIZE}")

def check_trailing_stop():
    global balance, positions
    closed = []
    
    for pos in positions[:]:
        price = get_price(pos["symbol"])
        if price == 0:
            continue
        
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        # Трейлинг-стоп
        if pos["peak_profit"] >= TRAILING_ACTIVATE:
            if pos["peak_profit"] - profit >= TRAILING_DISTANCE:
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

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>AUTO TRADING BOT</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
        .button{background:#0f0;color:#000;padding:8px 15px;margin:5px;cursor:pointer;border-radius:5px}
    </style>
</head>
<body>
<h1>🤖 AUTO TRADING BOT</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
<div class=card>
    <h2>💰 ПОРТФЕЛЬ</h2>
    <div class=stat><span>Баланс:</span><span id=balance>$0</span></div>
    <div class=stat><span>Автопилот:</span><span id=autopilot>ВКЛ</span></div>
    <div class=stat><span>Позиций:</span><span id=pos_count>0</span></div>
</div>
<div class=card>
    <h2>🎯 BUY СИГНАЛЫ (RSI &lt; 35)</h2>
    <div id=signals>Загрузка...</div>
</div>
<div class=card>
    <h2>📈 ПОЗИЦИИ</h2>
    <div id=positions>Нет</div>
</div>
</body>
<script>
async function update(){
    const r=await fetch('/data');
    const d=await r.json();
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    document.getElementById('pos_count').innerHTML=d.positions.length;
    let s='';
    for(let sig of d.buy_signals.slice(0,15)){
        s+=`<div class=stat><span>${sig.symbol}</span><span class=profit>BUY</span><span>${sig.confidence}%</span><span>RSI=${sig.rsi}</span><span>$${sig.price}</span></div>`;
    }
    document.getElementById('signals').innerHTML=s||'Нет сигналов';
    let p='';
    for(let pos of d.positions){
        p+=`<div class=stat><span>${pos.symbol}</span><span>${pos.profit?.toFixed(2)||0}%</span><span>$${pos.amount}</span></div>`;
    }
    document.getElementById('positions').innerHTML=p||'Нет позиций';
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
    buy = [{"symbol":k,"confidence":v["confidence"],"rsi":v["rsi"],"price":v["price"]} 
           for k,v in signals.items() if v["signal"]=="BUY"]
    buy.sort(key=lambda x: x["confidence"], reverse=True)
    # Добавляем текущую прибыль к позициям
    pos_data = []
    for p in positions:
        price = get_price(p["symbol"])
        profit = (price - p["entry_price"]) / p["entry_price"] * 100 if price > 0 else 0
        pos_data.append({"symbol": p["symbol"], "profit": profit, "amount": p["amount"]})
    return jsonify({
        "balance": round(balance, 2),
        "auto_pilot": auto_pilot,
        "buy_signals": buy[:30],
        "positions": pos_data
    })

@app.route('/cmd/auto')
def toggle_auto():
    global auto_pilot
    auto_pilot = not auto_pilot
    add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
    return "ok"

@app.route('/cmd/close')
def close_all():
    global balance, positions
    for pos in positions[:]:
        if market_sell(pos["symbol"], pos["amount"]):
            balance += pos["amount"]
    positions.clear()
    add_log("🔒 Все позиции закрыты")
    return "ok"

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
                    if market_sell(pos["symbol"], pos["amount"]):
                        balance += pos["amount"]
                positions.clear()
                add_log("🔒 Все позиции закрыты")
            elif cmd == 's':
                add_log(f"📊 Баланс: ${balance:.2f}, Позиций: {len(positions)}")
            elif cmd == 'q':
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
    
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=console_handler, daemon=True).start()
    
    balance = get_balance()
    
    add_log("🚀 AUTO TRADING BOT ЗАПУЩЕН")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log(f"📡 Монет: {len(COINS)}")
    add_log("🌐 http://localhost:5002")
    add_log("🎮 КОМАНДЫ: A - Автопилот | C - Закрыть всё | S - Статус | Q - Выход")
    
    last_scan = 0
    
    while running:
        try:
            balance = get_balance()
            
            if time.time() - last_scan > 10:
                scan_and_trade()
                last_scan = time.time()
            
            check_trailing_stop()
            
            # Консольный вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            buy_sigs = [(c,d) for c,d in signals.items() if d["signal"] == "BUY"]
            buy_sigs.sort(key=lambda x: x[1]["confidence"], reverse=True)
            
            print("\n" + "=" * 70)
            print("   🤖 AUTO TRADING BOT")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 70)
            print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   💰 БАЛАНС: ${balance:.2f}")
            print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
            print(f"   📊 ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
            
            if buy_sigs:
                print(f"\n   🟢 BUY СИГНАЛЫ (RSI < {RSI_BUY}):")
                for coin, data in buy_sigs[:10]:
                    print(f"      📈 {coin}: {data['confidence']:.0f}% | RSI={data['rsi']} | ${data['price']:.6f}")
            else:
                print(f"\n   ⏸️ Нет сигналов BUY")
            
            if positions:
                print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
                for pos in positions:
                    price = get_price(pos["symbol"])
                    profit = (price - pos["entry_price"]) / pos["entry_price"] * 100 if price > 0 else 0
                    print(f"      📈 {pos['symbol']}: {profit:+.2f}% | вход ${pos['entry_price']:.6f}")
            
            print("\n" + "=" * 70)
            print("   🎮 A - Автопилот | C - Закрыть всё | S - Статус | Q - Выход")
            print("   🌐 http://localhost:5002")
            print("=" * 70)
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            running = False
            add_log("🛑 Бот остановлен")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
