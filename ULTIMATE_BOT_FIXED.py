# -*- coding: utf-8 -*-
# ULTIMATE_BOT_FIXED.py - ПРОФЕССИОНАЛЬНАЯ ВЕРСИЯ

import time
import requests
import hmac
import hashlib
import threading
import logging
import sys
import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

# ============================================================
# ОТКЛЮЧАЕМ СТАНДАРТНЫЕ ЛОГИ FLASK
# ============================================================
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
cli = sys.modules.get('flask.cli')
if cli:
    cli.show_server_banner = lambda *args: None

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT",
    "ETCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT", "SUIUSDT",
    "SEIUSDT", "TRXUSDT", "XLMUSDT", "VETUSDT", "HBARUSDT", "ICPUSDT", "EGLDUSDT",
    "THETAUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT", "AXSUSDT", "RNDRUSDT", "IMXUSDT",
    "STXUSDT", "MKRUSDT", "CRVUSDT", "SNXUSDT", "COMPUSDT", "ZECUSDT", "DASHUSDT",
    "XMRUSDT", "EOSUSDT", "XTZUSDT", "KSMUSDT", "WAVESUSDT", "ALGOUSDT", "FLOWUSDT"
]

MAX_POSITIONS = 5
BUDGET_SHARE = 0.20
MIN_TRADE_USD = 5
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

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
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

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except: pass
    return 0

def get_klines(s, limit=50):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={s}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except: pass
    return []

def market_buy(s, amt):
    try:
        price = get_price(s)
        if price <= 0: return False
        if price < 1:
            qty = int(amt / price)
            if qty < 1: return False
        else:
            qty = round(amt / price, 6)
            if qty < 1e-6: return False
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

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:300]}, timeout=3)
    except: pass

def add_log(msg):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(logs) > 100: logs.pop()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def add_history(symbol, side, price, amount, profit=0):
    history.insert(0, {"time": datetime.now().strftime("%H:%M:%S"),
                       "symbol": symbol, "side": side, "price": round(price, 6),
                       "amount": round(amount, 2), "profit": round(profit, 2)})
    if len(history) > 50: history.pop()

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50
    g, l = [], []
    for i in range(1, period+1):
        d = prices[-i] - prices[-i-1]
        if d > 0: g.append(d)
        else: l.append(abs(d))
    ag = sum(g)/period if g else 0
    al = sum(l)/period if l else 0.001
    return 100 - (100/(1+ag/al))

def calc_macd(prices, fast=12, slow=26):
    if len(prices) < slow: return 0
    ema_fast = sum(prices[-fast:]) / fast
    ema_slow = sum(prices[-slow:]) / slow
    return ema_fast - ema_slow

def calc_bollinger(prices, period=20):
    if len(prices) < period: return 0.5
    sma = sum(prices[-period:]) / period
    var = sum((p - sma)**2 for p in prices[-period:]) / period
    std = var ** 0.5
    lower = sma - 2 * std
    upper = sma + 2 * std
    pos = (prices[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return pos

def analyze(s, p):
    prices = get_klines(s, 50)
    if len(prices) < 30: return "HOLD", 0, 50
    rsi = calc_rsi(prices)
    macd = calc_macd(prices)
    bb = calc_bollinger(prices)
    
    score = 0
    if rsi < RSI_BUY: score += 40
    if macd > 0: score += 25
    if bb < 0.2: score += 30
    sma5 = sum(prices[-5:])/5
    sma20 = sum(prices[-20:])/20
    if sma5 > sma20: score += 15
    
    if score > 35:
        conf = min(90, 60 + score)
        return "BUY", conf, rsi
    return "HOLD", 0, rsi

def get_pos(s):
    for p in positions:
        if p["symbol"] == s: return p
    return None

def auto_trade():
    global balance, positions
    if not auto_pilot: return
    if len(positions) >= MAX_POSITIONS: return
    invest = max(balance * BUDGET_SHARE, MIN_TRADE_USD)
    if invest < MIN_TRADE_USD or invest > balance: return
    
    candidates = []
    for sym, data in signals.items():
        if data["signal"] == "BUY" and get_pos(sym) is None and data["price"] > 0:
            candidates.append((sym, data["price"], data["confidence"]))
    
    if not candidates: return
    candidates.sort(key=lambda x: x[1])
    best_sym, best_price, best_conf = candidates[0]
    
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
            "symbol": best_sym, "entry_price": best_price, "invested": actual,
            "quantity": qty, "entry_time": time.time(),
            "peak_price": best_price, "peak_profit": 0, "confidence": best_conf
        })
        add_log(f"🟢 ПОКУПКА {best_sym}: ${actual:.2f}")

def check_sell():
    global balance, positions
    to_remove = []
    for pos in positions:
        price = get_price(pos["symbol"])
        if price <= 0: continue
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        if pos["peak_profit"] >= TRAILING_ACTIVATE and (pos["peak_profit"] - profit) >= TRAILING_DISTANCE:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"🎯 ТРЕЙЛИНГ-СТОП {pos['symbol']}: {profit:+.2f}%")
                add_history(pos["symbol"], "ТРЕЙЛИНГ-СТОП", price, pos["invested"], profit_usd)
                to_remove.append(pos)
        elif profit >= TAKE_PROFIT:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"🎉 ТЕЙК-ПРОФИТ {pos['symbol']}: {profit:+.2f}%")
                add_history(pos["symbol"], "ТЕЙК-ПРОФИТ", price, pos["invested"], profit_usd)
                to_remove.append(pos)
        elif profit <= -STOP_LOSS:
            if market_sell(pos["symbol"], pos["quantity"]):
                profit_usd = pos["invested"] * profit / 100
                balance += pos["invested"] + profit_usd
                add_log(f"🛑 СТОП-ЛОСС {pos['symbol']}: {profit:+.2f}%")
                add_history(pos["symbol"], "СТОП-ЛОСС", price, pos["invested"], profit_usd)
                to_remove.append(pos)
    for pos in to_remove: positions.remove(pos)

# ============================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head><title>TRADING BOT</title><meta http-equiv="refresh" content="5"><style>
body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
.card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
.stat{display:flex;justify-content:space-between;padding:5px 0}
.big-number{font-size:2em;text-align:center;margin:10px 0}
.btn{background:#0f0;color:#000;padding:8px 15px;margin:5px;cursor:pointer;border-radius:5px;font-weight:bold}
.btn-danger{background:#f00;color:#fff}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 5px;border-bottom:1px solid #333;text-align:left}
th{color:#0f0;border-bottom:2px solid #0f0}
.signal-buy{color:#0f0;font-weight:bold}
.log-panel{background:#000;height:200px;overflow:auto;font-size:11px;padding:10px}
</style></head>
<body>
<h1>🤖 ULTIMATE TRADING BOT</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
<div class="card">
    <div class="big-number" id="balance">$0</div>
    <div class="stat"><span>Автопилот:</span><span id="autopilot">ВКЛ</span></div>
    <div class="stat"><span>Позиций:</span><span id="pos_count">0</span></div>
    <button class="btn" onclick="fetch('/cmd/auto')">🤖 АВТОПИЛОТ</button>
    <button class="btn btn-danger" onclick="fetch('/cmd/close')">🔒 ЗАКРЫТЬ ВСЁ</button>
    <button class="btn" onclick="showBuy()">🟢 КУПИТЬ</button>
    <button class="btn" onclick="showSell()">🔴 ПРОДАТЬ</button>
</div>
<div class="card"><h3>🎯 СИГНАЛЫ BUY</h3><div id="signals">Загрузка...</div></div>
<div class="card"><h3>📊 ПОЗИЦИИ</h3><div id="positions">Нет</div></div>
<div class="card"><h3>📋 ИСТОРИЯ</h3><div id="history">Нет</div></div>
<div class="card"><h3>📋 ЛОГИ</h3><div id="logs" class="log-panel">Загрузка...</div></div>
<script>
function showBuy(){let c=prompt("Монета:","XTZUSDT"); if(c){let a=prompt("Сумма:","10"); if(a) fetch(`/cmd/buy?symbol=${c}&amount=${a}`);}}
function showSell(){let c=prompt("Монета:",""); if(c) fetch(`/cmd/sell?symbol=${c}`);}
function update(){
    fetch('/data').then(r=>r.json()).then(d=>{
        document.getElementById('balance').innerHTML='$'+d.balance;
        document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
        document.getElementById('pos_count').innerHTML=d.positions.length;
        let s='<table><thead><tr><th>Монета</th><th>Сигнал</th><th>%</th><th>RSI</th><th>Цена</th></tr></thead><tbody>';
        for(let sig of d.buy_signals.slice(0,30)){
            s+=`<tr><td><b>${sig.symbol}</b></td><td class="signal-buy">BUY</td><td>${sig.confidence}%</td><td>${sig.rsi}</td><td>$${sig.price}</td></tr>`;
        }
        s+='</tbody></table>';
        document.getElementById('signals').innerHTML=s;
        let p='<tr><thead><tr><th>Монета</th><th>Прибыль</th><th>Вложено</th></tr></thead><tbody>';
        for(let pos of d.positions){
            let cls = pos.profit>=0 ? 'profit' : 'loss';
            p+=`<tr><td>${pos.symbol}</td><td class="${cls}">${pos.profit.toFixed(2)}%</td><td>$${pos.invested}</td></tr>`;
        }
        p+='</tbody></table>';
        document.getElementById('positions').innerHTML=p;
        let h='<tr><thead><tr><th>Время</th><th>Монета</th><th>Тип</th><th>Прибыль</th></tr></thead><tbody>';
        for(let hist of d.history.slice(0,20)){
            let cls = hist.profit>=0 ? 'profit' : 'loss';
            h+=`<tr><td>${hist.time}</td><td>${hist.symbol}</td><td>${hist.side}</td><td class="${cls}">${hist.profit>0?'+':''}${hist.profit}</td></tr>`;
        }
        h+='</tbody></table>';
        document.getElementById('history').innerHTML=h;
        let l='';
        for(let log of d.logs.slice(0,30)) l+=`<div>[${log.time}] ${log.msg}</div>`;
        document.getElementById('logs').innerHTML=l;
    });
}
setInterval(update,2000);update();
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
        cur = get_price(p["symbol"])
        profit = (cur - p["entry_price"]) / p["entry_price"] * 100 if cur>0 else 0
        pos_data.append({"symbol":p["symbol"], "profit":profit, "invested":p["invested"]})
    return jsonify({
        "balance":round(balance,2), "auto_pilot":auto_pilot,
        "buy_signals":buy[:50], "positions":pos_data,
        "history":history[:30], "logs":logs[:50]
    })

@app.route('/cmd/auto')
def cmd_auto(): global auto_pilot; auto_pilot=not auto_pilot; add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}"); return "ok"

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
            positions.append({"symbol":sym,"entry_price":price,"invested":actual,"quantity":qty,"entry_time":time.time(),"peak_price":price,"peak_profit":0})
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
            add_log(f"🔴 РУЧНАЯ ПРОДАЖА {sym}")
            break
    return "ok"

# ============================================================
# КРАСИВЫЙ КОНСОЛЬНЫЙ ДАШБОРД
# ============================================================

def print_console_dashboard():
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Шапка
    print("\n" + "█" * 80)
    print("█   🤖 ABSOLUTE ULTIMATE TRADING BOT")
    print("█   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
    print("█" * 80)
    
    # Основная статистика
    win_rate = (len([h for h in history if h["profit"] > 0]) / max(len(history), 1)) * 100
    print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   💰 БАЛАНС: ${balance:.2f}")
    print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛЮЧЁН' if auto_pilot else '❌ ВЫКЛЮЧЕН'}")
    print(f"   📊 ПОЗИЦИЙ: {len(positions)}/{MAX_POSITIONS}")
    print(f"   🏆 ВСЕГО СДЕЛОК: {len(history)} | ВИНРЕЙТ: {win_rate:.0f}%")
    print(f"   🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    
    # Лучшие сигналы на покупку
    buy_list = [(sym, data) for sym, data in signals.items() if data["signal"] == "BUY"]
    buy_list.sort(key=lambda x: x[1]["confidence"], reverse=True)
    
    if buy_list:
        print(f"\n   🟢 ТОП-10 СИГНАЛОВ НА ПОКУПКУ:")
        print(f"   {'─' * 78}")
        print(f"   {'Монета':<12} {'Сигнал':<8} {'Уверенность':<12} {'RSI':<8} {'Цена':<12}")
        print(f"   {'─' * 78}")
        for sym, data in buy_list[:10]:
            print(f"   {sym:<12} 📈 {data['signal']:<5} {data['confidence']:>5.0f}%      {data['rsi']:>5.0f}     ${data['price']:>10.2f}")
    
    # Открытые позиции
    if positions:
        print(f"\n   📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
        print(f"   {'─' * 78}")
        print(f"   {'Монета':<12} {'Тип':<8} {'Вход':<12} {'Текущая':<12} {'Прибыль':<12} {'Вложено':<12}")
        print(f"   {'─' * 78}")
        for pos in positions:
            cur = get_price(pos["symbol"])
            profit = (cur - pos["entry_price"]) / pos["entry_price"] * 100 if cur > 0 else 0
            profit_color = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
            print(f"   {pos['symbol']:<12} {profit_color}       ${pos['entry_price']:>8.4f}  ${cur:>8.4f}  {profit:>+6.2f}%     ${pos['invested']:>8.2f}")
    
    # Последние транзакции
    if history:
        print(f"\n   📋 ПОСЛЕДНИЕ ТРАНЗАКЦИИ:")
        print(f"   {'─' * 78}")
        print(f"   {'Время':<12} {'Монета':<12} {'Тип':<16} {'Прибыль':<12}")
        print(f"   {'─' * 78}")
        for h in history[:5]:
            profit_symbol = "📈 +" if h["profit"] > 0 else "📉 " if h["profit"] < 0 else "⚪ "
            print(f"   {h['time']:<12} {h['symbol']:<12} {h['side']:<16} {profit_symbol}{h['profit']:>6.2f}$")
    
    # Последние логи
    if logs:
        print(f"\n   📡 ПОСЛЕДНИЕ СОБЫТИЯ:")
        print(f"   {'─' * 78}")
        for log_entry in logs[:5]:
            print(f"   [{log_entry['time']}] {log_entry['msg']}")
    
    # Команды
    print(f"\n   {'─' * 78}")
    print(f"   🎮 КОМАНДЫ: [A] Автопилот  [C] Закрыть всё  [S] Статус  [T] Telegram  [Q] Выход")
    print(f"   {'─' * 78}\n")

# ============================================================
# КОНСОЛЬНЫЙ ОБРАБОТЧИК КОМАНД
# ============================================================

def console_handler():
    global auto_pilot, balance, positions, running
    while running:
        try:
            if sys.stdin.isatty():
                cmd = sys.stdin.read(1).lower()
                if cmd == 'a':
                    auto_pilot = not auto_pilot
                    add_log(f"🤖 Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
                elif cmd == 'c':
                    for p in positions[:]:
                        market_sell(p["symbol"], p["quantity"])
                        balance += p["invested"]
                    positions.clear()
                    add_log("🔒 Все позиции закрыты")
                elif cmd == 's':
                    add_log(f"📊 Баланс: ${balance:.2f}, Позиций: {len(positions)}")
                elif cmd == 't':
                    send_telegram(f"🤖 БОТ АКТИВЕН\nБаланс: ${balance:.2f}")
                    add_log("📱 Telegram отправлен")
                elif cmd == 'q':
                    running = False
                    add_log("🛑 Бот остановлен")
                    break
        except:
            pass
        time.sleep(0.1)

# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

def main():
    global balance, running
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False, threaded=True), daemon=True).start()
    threading.Thread(target=console_handler, daemon=True).start()
    
    balance = get_balance()
    
    print("="*60)
    print("   🤖 ULTIMATE TRADING BOT ЗАПУЩЕН")
    print(f"   Баланс: ${balance:.2f}")
    print(f"   Монет: {len(COINS)}")
    print("   Веб: http://localhost:5002")
    print("   🎮 КОМАНДЫ: A - Автопилот | C - Закрыть всё | S - Статус | T - Telegram | Q - Выход")
    print("="*60)
    
    last = 0
    while running:
        try:
            balance = get_balance()
            if time.time() - last >= SCAN_INTERVAL:
                for coin in COINS:
                    price = get_price(coin)
                    if price == 0: continue
                    sig, conf, rsi = analyze(coin, price)
                    signals[coin] = {"signal": sig, "confidence": conf, "price": price, "rsi": round(rsi,1)}
                auto_trade()
                last = time.time()
            check_sell()
            print_console_dashboard()
            time.sleep(5)
        except KeyboardInterrupt: 
            running = False
            break
        except Exception as e: 
            add_log(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()