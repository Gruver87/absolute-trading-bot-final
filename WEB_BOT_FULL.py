# -*- coding: utf-8 -*-
# WEB_BOT_FULL.py - ПОЛНАЯ ВЕРСИЯ С ВЕБ-ИНТЕРФЕЙСОМ

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

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

MAX_POSITIONS = 5
BUDGET_SHARE = 0.2
MIN_TRADE = 5
RSI_BUY = 35
STOP_LOSS = 3.5
TAKE_PROFIT = 7.0
TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0
SCAN_INTERVAL = 10

balance = 0.0
positions = []
signals = {}
logs = []
history = []
auto_pilot = True
running = True

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

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except: pass
    return 0

def get_klines(s, limit=100):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={s}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except: pass
    return []

def market_buy(s, amount_usd):
    try:
        price = get_price(s)
        if price == 0: return False
        if price < 1:
            qty = int(amount_usd / price)
            if qty < 1: return False
        else:
            qty = round(amount_usd / price, 6)
            if qty < 0.000001: return False
        t = int(time.time()*1000)
        params = f"symbol={s}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def market_sell(s, qty):
    try:
        t = int(time.time()*1000)
        params = f"symbol={s}&side=SELL&type=MARKET&quantity={qty}&timestamp={t}"
        sig = sign(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except: return False

def add_log(msg):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(logs) > 100: logs.pop()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def add_history(symbol, side, price, amount, profit=0):
    history.insert(0, {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "symbol": symbol, "side": side, "price": price,
                       "amount": amount, "profit": profit})
    if len(history) > 50: history.pop()

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50
    gains, losses = [], []
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0: gains.append(diff)
        else: losses.append(abs(diff))
    ag = sum(gains)/period if gains else 0
    al = sum(losses)/period if losses else 0.001
    return 100 - (100/(1+ag/al))

def analyze(s, p):
    prices = get_klines(s, 50)
    if len(prices) < 30: return "HOLD", 0, 50
    rsi = calc_rsi(prices)
    if rsi < RSI_BUY:
        conf = min(90, 70 + (RSI_BUY - rsi))
        return "BUY", conf, rsi
    return "HOLD", 0, rsi

def predict_trend(s):
    prices = get_klines(s, 50)
    if len(prices) < 30: return "Нет данных", 0, 50
    rsi = calc_rsi(prices)
    sma5 = sum(prices[-5:])/5
    sma20 = sum(prices[-20:])/20
    if rsi < 30: return "↑ Сильный рост (перепродано)", 85, rsi
    if rsi < 40: return "↑ Рост", 70, rsi
    if rsi > 70: return "↓ Сильное падение (перекуплено)", 85, rsi
    if rsi > 60: return "↓ Падение", 70, rsi
    if sma5 > sma20: return "↗ Восходящий тренд", 60, rsi
    if sma5 < sma20: return "↘ Нисходящий тренд", 60, rsi
    return "→ Флэт", 50, rsi

def get_position(s):
    for p in positions:
        if p["symbol"] == s: return p
    return None

def scan_and_buy():
    global signals, balance, positions
    for coin in COINS:
        price = get_price(coin)
        if price == 0: continue
        sig, conf, rsi = analyze(coin, price)
        signals[coin] = {"signal": sig, "confidence": conf, "price": price, "rsi": round(rsi, 1)}
    if not auto_pilot: return
    if len(positions) >= MAX_POSITIONS: return
    invest = max(balance * BUDGET_SHARE, MIN_TRADE)
    if invest <= 0 or invest > balance: return
    buy_list = [(s,d) for s,d in signals.items() if d["signal"] == "BUY" and get_position(s) is None]
    if not buy_list: return
    buy_list.sort(key=lambda x: (-x[1]["confidence"], x[1]["price"]))
    best = buy_list[0][0]
    price = signals[best]["price"]
    if price <= 0: return
    if market_buy(best, invest):
        balance -= invest
        if price < 1:
            qty = int(invest / price)
        else:
            qty = invest / price
        positions.append({"symbol": best, "entry_price": price, "invested": invest,
                         "quantity": qty, "entry_time": time.time(),
                         "peak_price": price, "peak_profit": 0})
        add_log(f"🟢 ПОКУПКА {best}: ${invest:.2f} по {price:.6f}")

def manual_buy(symbol, amount_usd):
    global balance, positions
    price = get_price(symbol)
    if price == 0: return "Нет цены"
    if amount_usd > balance: return f"Не хватает! Баланс: ${balance:.2f}"
    if price < 1:
        qty = int(amount_usd / price)
        actual = qty * price
    else:
        qty = amount_usd / price
        actual = amount_usd
    if market_buy(symbol, actual):
        balance -= actual
        positions.append({"symbol": symbol, "entry_price": price, "invested": actual,
                         "quantity": qty, "entry_time": time.time(),
                         "peak_price": price, "peak_profit": 0})
        add_history(symbol, "РУЧНАЯ ПОКУПКА", price, actual)
        add_log(f"🔨 РУЧНАЯ ПОКУПКА {symbol}: ${actual:.2f}")
        return f"Куплено {symbol} на ${actual:.2f}"
    return "Ошибка покупки"

def manual_sell(symbol):
    global balance, positions
    pos = get_position(symbol)
    if not pos: return "Нет позиции"
    price = get_price(symbol)
    if price == 0: return "Нет цены"
    profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
    profit_usd = pos["invested"] * profit / 100
    if market_sell(symbol, pos["quantity"]):
        balance += pos["invested"] + profit_usd
        add_history(symbol, "РУЧНАЯ ПРОДАЖА", price, pos["invested"], profit_usd)
        add_log(f"🔨 РУЧНАЯ ПРОДАЖА {symbol}: {profit:+.2f}%")
        positions.remove(pos)
        return f"Продано {symbol} | Прибыль: {profit:+.2f}%"
    return "Ошибка продажи"

def check_and_sell():
    global balance, positions
    to_remove = []
    for pos in positions:
        price = get_price(pos["symbol"])
        if price == 0: continue
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        should_sell = False
        reason = ""
        if pos["peak_profit"] >= TRAILING_ACTIVATE and (pos["peak_profit"] - profit) >= TRAILING_DISTANCE:
            should_sell, reason = True, "trailing"
        elif profit >= TAKE_PROFIT:
            should_sell, reason = True, "tp"
        elif profit <= -STOP_LOSS:
            should_sell, reason = True, "sl"
        if should_sell:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                emoji = "🎯" if reason == "trailing" else ("🎉" if reason == "tp" else "🛑")
                add_log(f"{emoji} {reason.upper()} {pos['symbol']}: {profit:+.2f}%")
                add_history(pos["symbol"], "АВТОПРОДАЖА", price, pos["invested"], profit_usd)
                to_remove.append(pos)
    for pos in to_remove: positions.remove(pos)

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>ABSOLUTE TRADING BOT</title>
    <meta http-equiv="refresh" content="5">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:linear-gradient(135deg,#0a0a0a 0%,#0d1a0d 50%,#0a0a0a 100%);font-family:monospace;color:#0f0;padding:20px}
        .container{max-width:1400px;margin:0 auto}
        .header{text-align:center;padding:20px;border-bottom:2px solid #0f0;margin-bottom:20px}
        .header h1{font-size:1.8em;text-shadow:0 0 10px #0f0}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:20px;margin-bottom:20px}
        .card{background:rgba(0,0,0,0.75);border:1px solid #0f0;border-radius:15px;padding:20px}
        .card h3{margin-bottom:15px;border-left:3px solid #0f0;padding-left:12px}
        .stat{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #333}
        .big-number{font-size:2.5em;font-weight:bold;text-align:center;margin:15px 0}
        .btn{background:#0f0;color:#000;border:none;padding:10px 20px;margin:5px;cursor:pointer;border-radius:8px;font-weight:bold}
        .btn:hover{transform:scale(1.02);box-shadow:0 0 15px #0f0}
        .btn-danger{background:#f00;color:#fff}
        .btn-warning{background:#ff0;color:#000}
        .btn-group{display:flex;flex-wrap:wrap;gap:10px;margin-top:15px}
        .signal-buy{color:#0f0;background:rgba(0,255,0,0.1);padding:2px 8px;border-radius:5px}
        .profit{color:#0f0}.loss{color:#f00}
        table{width:100%;font-size:13px;border-collapse:collapse}
        th,td{padding:8px 5px;text-align:left;border-bottom:1px solid #333}
        th{color:#0f0;border-bottom:2px solid #0f0}
        .log-panel{background:#000;height:200px;overflow-y:auto;font-size:11px;padding:12px;border-radius:8px}
        .footer{text-align:center;margin-top:30px;padding:20px;color:#666;font-size:11px}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🤖 ABSOLUTE TRADING BOT</h1>
        <p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
    </div>
    <div class="grid">
        <div class="card">
            <h3>💰 ПОРТФЕЛЬ</h3>
            <div class="big-number" id="balance">$0.00</div>
            <div class="stat"><span>Автопилот:</span><span id="autopilot">ВКЛ</span></div>
            <div class="stat"><span>Позиций:</span><span id="pos_count">0/5</span></div>
            <div class="btn-group">
                <button class="btn btn-warning" onclick="fetch('/cmd/auto')">🤖 АВТОПИЛОТ</button>
                <button class="btn btn-danger" onclick="fetch('/cmd/close')">🔒 ЗАКРЫТЬ ВСЁ</button>
            </div>
        </div>
        <div class="card">
            <h3>📈 ТОП ВАЛЮТ</h3>
            <div class="stat"><span>BTC:</span><span id="btc">$---</span></div>
            <div class="stat"><span>ETH:</span><span id="eth">$---</span></div>
            <div class="stat"><span>SOL:</span><span id="sol">$---</span></div>
            <div class="stat"><span>BNB:</span><span id="bnb">$---</span></div>
            <div class="btn-group">
                <button class="btn" onclick="showBuyModal()">🟢 КУПИТЬ ВРУЧНУЮ</button>
                <button class="btn" onclick="showSellModal()">🔴 ПРОДАТЬ ВРУЧНУЮ</button>
            </div>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <h3>🎯 BUY СИГНАЛЫ (RSI&lt;35)</h3>
            <div id="signals" style="max-height:300px;overflow:auto">Загрузка...</div>
        </div>
        <div class="card">
            <h3>📊 ПОЗИЦИИ</h3>
            <div id="positions" style="max-height:300px;overflow:auto">Нет</div>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <h3>📋 ИСТОРИЯ СДЕЛОК</h3>
            <div id="history" style="max-height:300px;overflow:auto">Нет</div>
        </div>
        <div class="card">
            <h3>📋 ЛОГИ</h3>
            <div id="logs" class="log-panel">Загрузка...</div>
        </div>
    </div>
    <div class="footer">
        <p>⚡ Трейлинг-стоп: активация +3%, отступ 2% | 🛡️ Стоп-лосс: -3.5% | 🎯 Тейк-профит: +7%</p>
    </div>
</div>
<script>
function showBuyModal(){
    let coin = prompt("Введите монету (например SNXUSDT):", "SNXUSDT");
    if(coin){
        let amount = prompt("Сумма в USDT (мин 5):", "10");
        if(amount && amount>=5){
            fetch(`/cmd/buy?symbol=${coin}&amount=${amount}`).then(()=>setTimeout(update,500));
        }
    }
}
function showSellModal(){
    let coin = prompt("Введите монету для продажи:", "");
    if(coin) fetch(`/cmd/sell?symbol=${coin}`).then(()=>setTimeout(update,500));
}
function update(){
    fetch('/data').then(r=>r.json()).then(d=>{
        document.getElementById('balance').innerHTML='$'+d.balance;
        document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
        document.getElementById('pos_count').innerHTML=d.positions.length+'/5';
        document.getElementById('btc').innerHTML='$'+d.btc;
        document.getElementById('eth').innerHTML='$'+d.eth;
        document.getElementById('sol').innerHTML='$'+d.sol;
        document.getElementById('bnb').innerHTML='$'+d.bnb;
        let s='<table><tr><th>Монета</th><th>Сигнал</th><th>%</th><th>RSI</th><th>Цена</th></tr>';
        for(let sig of d.buy_signals.slice(0,15)){
            s+=`<tr><td><b>${sig.symbol}</b></td><td><span class="signal-buy">BUY</span></td><td>${sig.confidence}%</td><td>${sig.rsi}</td><td>$${sig.price}</td></tr>`;
        }
        s+='</table>';
        document.getElementById('signals').innerHTML=s||'Нет сигналов';
        let p='<table><tr><th>Монета</th><th>Прибыль</th><th>Вложено</th></tr>';
        for(let pos of d.positions){
            p+=`<tr><td>${pos.symbol}</td><td class="${pos.profit>=0?'profit':'loss'}">${pos.profit.toFixed(2)}%</td><td>$${pos.invested.toFixed(2)}</td></tr>`;
        }
        p+='</table>';
        document.getElementById('positions').innerHTML=p||'Нет позиций';
        let h='<table><tr><th>Время</th><th>Монета</th><th>Тип</th><th>Прибыль</th></tr>';
        for(let hist of d.history.slice(0,20)){
            h+=`<tr><td>${hist.time}</td><td>${hist.symbol}</td><td>${hist.side}</td><td class="${hist.profit>=0?'profit':'loss'}">${hist.profit>0?'+':''}${hist.profit.toFixed(2)}</td></tr>`;
        }
        h+='</table>';
        document.getElementById('history').innerHTML=h||'Нет истории';
        let l='';
        for(let log of d.logs.slice(0,30)) l+=`<div>[${log.time}] ${log.msg}</div>`;
        document.getElementById('logs').innerHTML=l;
    });
}
setInterval(update,3000);
update();
</script>
</body>
</html>
'''

@app.route('/')
def index(): return render_template_string(HTML)

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
        "balance": round(balance,2), "auto_pilot": auto_pilot,
        "buy_signals": buy[:30], "positions": pos_data,
        "history": history[:30], "logs": logs[:50],
        "btc": get_price("BTCUSDT"), "eth": get_price("ETHUSDT"),
        "sol": get_price("SOLUSDT"), "bnb": get_price("BNBUSDT")
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
        market_sell(pos["symbol"], pos["quantity"])
        balance += pos["invested"]
    positions.clear()
    add_log("🔒 Все позиции закрыты")
    return "ok"

@app.route('/cmd/buy')
def buy_route():
    symbol = request.args.get('symbol', '')
    amount = float(request.args.get('amount', 0))
    if symbol and amount > 0:
        msg = manual_buy(symbol, amount)
        add_log(msg)
    return "ok"

@app.route('/cmd/sell')
def sell_route():
    symbol = request.args.get('symbol', '')
    if symbol:
        msg = manual_sell(symbol)
        add_log(msg)
    return "ok"

def main():
    global balance, running
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    balance = get_balance()
    add_log("🚀 FULL WEB BOT ЗАПУЩЕН")
    add_log(f"💰 Баланс: ${balance:.2f}")
    add_log("🌐 http://localhost:5002")
    last_scan = 0
    while running:
        try:
            balance = get_balance()
            if time.time() - last_scan >= SCAN_INTERVAL:
                scan_and_buy()
                last_scan = time.time()
            check_and_sell()
            time.sleep(3)
        except KeyboardInterrupt:
            running = False
            add_log("🛑 Бот остановлен")
            break
        except Exception as e:
            add_log(f"⚠️ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
