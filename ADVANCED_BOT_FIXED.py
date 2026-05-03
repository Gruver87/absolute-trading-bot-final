# -*- coding: utf-8 -*-
# ADVANCED_BOT_FIXED.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from collections import deque

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

COINS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
    "AVAXUSDT","DOTUSDT","LINKUSDT","MATICUSDT","UNIUSDT","ATOMUSDT","LTCUSDT",
    "ETCUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","FILUSDT","SUIUSDT",
    "SEIUSDT","TRXUSDT","XLMUSDT","VETUSDT","HBARUSDT","ICPUSDT","EGLDUSDT",
    "THETAUSDT","SANDUSDT","MANAUSDT","GALAUSDT","AXSUSDT","RNDRUSDT","IMXUSDT",
    "STXUSDT","MKRUSDT","CRVUSDT","SNXUSDT","COMPUSDT","ZECUSDT","DASHUSDT",
    "XMRUSDT","EOSUSDT","XTZUSDT","KSMUSDT","WAVESUSDT","ALGOUSDT","FLOWUSDT"
]

# ============================================================
# ПАРАМЕТРЫ
# ============================================================

MAX_POSITIONS = 5
BUDGET_SHARE = 0.2
RSI_BUY = 35
STOP_LOSS = 3.5
TAKE_PROFIT = 7.0
TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0
SCAN_INTERVAL = 10

# ============================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================================

balance = 0.0
positions = []
signals = {}
logs = []
auto_pilot = True
running = True

# ============================================================
# БАЗОВЫЕ ФУНКЦИИ
# ============================================================

def sign(params):
    return hmac.new(MEXC_API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_balance():
    try:
        t = int(time.time()*1000)
        sig = sign(f"timestamp={t}")
        resp = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                            headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if resp.status_code == 200:
            for b in resp.json().get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except:
        pass
    return 0

def get_price(symbol):
    try:
        resp = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if resp.status_code == 200:
            return float(resp.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(symbol, limit=50):
    try:
        resp = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=10)
        if resp.status_code == 200:
            return [float(c[4]) for c in resp.json()]
    except:
        pass
    return []

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
    if len(prices) < period+1:
        return 50
    gains, losses = [], []
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains)/period if gains else 0
    avg_loss = sum(losses)/period if losses else 0.001
    return 100 - (100/(1 + avg_gain/avg_loss))

# ============================================================
# АНАЛИЗ
# ============================================================

def analyze_symbol(symbol, price):
    prices = get_klines(symbol, 50)
    if len(prices) < 30:
        return "HOLD", 0, 50
    rsi = calc_rsi(prices)
    if rsi < RSI_BUY:
        confidence = min(90, 70 + (RSI_BUY - rsi))
        return "BUY", confidence, rsi
    return "HOLD", 0, rsi

# ============================================================
# ТОРГОВЛЯ
# ============================================================

def get_position(symbol):
    for p in positions:
        if p["symbol"] == symbol:
            return p
    return None

def calculate_investment_amount():
    available = balance
    if available <= 0:
        return 0
    invest = max(available * BUDGET_SHARE, 5)
    return min(invest, available * 0.5)

def market_buy(symbol, amount_usd):
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        quantity = amount_usd / price
        quantity = round(quantity, 8)
        if quantity <= 0:
            return False
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={t}"
        sig = sign(params)
        resp = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                             headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if resp.status_code == 200:
            add_log(f"? КУПИЛ {symbol} на ${amount_usd:.2f}")
            return True
    except Exception as e:
        add_log(f"? Ошибка покупки {symbol}: {e}")
    return False

def market_sell(symbol, quantity):
    try:
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={t}"
        sig = sign(params)
        resp = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                             headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if resp.status_code == 200:
            add_log(f"? ПРОДАЛ {symbol}")
            return True
    except Exception as e:
        add_log(f"? Ошибка продажи {symbol}: {e}")
    return False

def scan_and_trade():
    global signals, balance, positions
    
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        signal, conf, rsi = analyze_symbol(coin, price)
        signals[coin] = {"signal": signal, "confidence": conf, "price": price, "rsi": round(rsi, 1)}
    
    if not auto_pilot:
        return
    if len(positions) >= MAX_POSITIONS:
        return
    
    invest_amount = calculate_investment_amount()
    if invest_amount <= 0 or invest_amount > balance:
        return
    
    candidates = [(sym, data) for sym, data in signals.items() if data["signal"] == "BUY" and get_position(sym) is None]
    if not candidates:
        return
    candidates.sort(key=lambda x: x[1]["confidence"], reverse=True)
    best = candidates[0]
    sym = best[0]
    price = best[1]["price"]
    if price <= 0:
        return
    
    if market_buy(sym, invest_amount):
        balance -= invest_amount
        positions.append({
            "symbol": sym,
            "entry_price": price,
            "invested": invest_amount,
            "entry_time": time.time(),
            "peak_price": price,
            "peak_profit": 0
        })
        add_log(f"?? НОВАЯ ПОЗИЦИЯ: {sym}, вложено ${invest_amount:.2f}")

def update_trailing_stop():
    global balance, positions
    to_remove = []
    for pos in positions:
        sym = pos["symbol"]
        price = get_price(sym)
        if price == 0:
            continue
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        # Проверка на закрытие
        close = False
        reason = ""
        if pos["peak_profit"] >= TRAILING_ACTIVATE and (pos["peak_profit"] - profit) >= TRAILING_DISTANCE:
            close = True
            reason = "trailing"
        elif profit >= TAKE_PROFIT:
            close = True
            reason = "tp"
        elif profit <= -STOP_LOSS:
            close = True
            reason = "sl"
        if close:
            quantity = pos["invested"] / pos["entry_price"]
            if market_sell(sym, quantity):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"{'??' if reason=='trailing' else ('??' if reason=='tp' else '??')} {reason.upper()} {sym}: {profit:+.2f}% (+${profit_usd:.2f})")
                to_remove.append(pos)
    for pos in to_remove:
        positions.remove(pos)

# ============================================================
# ВЕБ-СЕРВЕР
# ============================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>ADVANCED BOT</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
    </style>
</head>
<body>
<h1>?? ADVANCED BOT</h1>
<p>?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
<div class=card>
    <h2>?? ПОРТФЕЛЬ</h2>
    <div class=stat><span>Баланс:</span><span id=balance>$0</span></div>
    <div class=stat><span>Автопилот:</span><span id=autopilot>ВКЛ</span></div>
    <div class=stat><span>Позиций:</span><span id=pos_count>0</span></div>
</div>
<div class=card>
    <h2>?? BUY СИГНАЛЫ (RSI&lt;35)</h2>
    <div id=signals>Загрузка...</div>
</div>
<div class=card>
    <h2>?? ПОЗИЦИИ</h2>
    <div id=positions>Нет</div>
</div>
<script>
async function update(){
    const r=await fetch('/data');
    const d=await r.json();
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'? ВКЛ':'? ВЫКЛ';
    document.getElementById('pos_count').innerHTML=d.positions.length;
    let s='';
    for(let sig of d.buy_signals.slice(0,15)){
        s+=`<div class=stat><span>${sig.symbol}</span><span class=profit>BUY</span><span>${sig.confidence}%</span><span>RSI=${sig.rsi}</span><span>$${sig.price}</span></div>`;
    }
    document.getElementById('signals').innerHTML=s||'Нет сигналов';
    let p='';
    for(let pos of d.positions){
        p+=`<div class=stat><span>${pos.symbol}</span><span>${pos.profit?.toFixed(2)||0}%</span><span>$${pos.invested}</span></div>`;
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
    buy = [{"symbol":k,"confidence":v["confidence"],"rsi":v["rsi"],"price":v["price"]} for k,v in signals.items() if v["signal"]=="BUY"]
    buy.sort(key=lambda x: x["confidence"], reverse=True)
    pos_data = []
    for p in positions:
        price = get_price(p["symbol"])
        profit = (price - p["entry_price"]) / p["entry_price"] * 100 if price > 0 else 0
        pos_data.append({"symbol": p["symbol"], "profit": profit, "invested": p["invested"]})
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
    add_log(f"?? Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
    return "ok"

@app.route('/cmd/close')
def close_all():
    global balance, positions
    for pos in positions[:]:
        qty = pos["invested"] / pos["entry_price"]
        market_sell(pos["symbol"], qty)
    positions.clear()
    add_log("?? Все позиции закрыты")
    return "ok"

def console_handler():
    global auto_pilot, balance, positions, running
    while running:
        try:
            cmd = input().strip().lower()
            if cmd == 'a':
                auto_pilot = not auto_pilot
                add_log(f"?? Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
            elif cmd == 'c':
                for pos in positions[:]:
                    qty = pos["invested"] / pos["entry_price"]
                    market_sell(pos["symbol"], qty)
                positions.clear()
                add_log("?? Все позиции закрыты")
            elif cmd == 's':
                add_log(f"?? Баланс: ${balance:.2f}, Позиций: {len(positions)}")
            elif cmd == 'q':
                running = False
                add_log("?? Бот остановлен")
                break
        except:
            pass
        time.sleep(0.1)

# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

def main():
    global balance, running
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=console_handler, daemon=True).start()
    balance = get_balance()
    add_log("?? ADVANCED BOT ЗАПУЩЕН")
    add_log(f"?? Баланс: ${balance:.2f}")
    add_log(f"?? Монет: {len(COINS)}")
    add_log("?? http://localhost:5002")
    add_log("?? КОМАНДЫ: A - Автопилот | C - Закрыть всё | S - Статус | Q - Выход")
    
    last_scan = 0
    while running:
        try:
            balance = get_balance()
            if time.time() - last_scan >= SCAN_INTERVAL:
                scan_and_trade()
                last_scan = time.time()
            update_trailing_stop()
            time.sleep(3)
        except KeyboardInterrupt:
            running = False
            add_log("?? Бот остановлен")
            break
        except Exception as e:
            add_log(f"?? Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
