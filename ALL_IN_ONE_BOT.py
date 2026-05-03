# -*- coding: utf-8 -*-
# ALL_IN_ONE_BOT.py - БОТ + ВЕБ-ДАШБОРД В ОДНОМ ФАЙЛЕ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
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
# ТОРГУЕМЫЕ МОНЕТЫ
# ============================================================================

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT",
    "ATOMUSDT", "LTCUSDT", "ETCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "FILUSDT", "SUIUSDT", "SEIUSDT", "TRXUSDT", "XLMUSDT"
]

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

TRADE_SIZE = 10
MAX_POSITIONS = 3
MIN_CONFIDENCE = 55
COOLDOWN_SECONDS = 30
POSITION_TIMEOUT = 7200

RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
STOP_LOSS_PCT = 3.5

TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0

MAX_DAILY_LOSS = 20.0
MAX_CONSECUTIVE_LOSSES = 5
MIN_BALANCE = 10

# ============================================================================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ============================================================================

bot_data = {
    "balance": 0,
    "total_profit": 0,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "win_rate": 0,
    "daily_pnl": 0,
    "drawdown": 0,
    "auto_pilot": True,
    "positions": [],
    "signals": [],
    "logs": [],
    "tracking_coins": len(COINS),
    "mode": "REAL"
}

# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def sign(params):
    return hmac.new(MEXC_API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_balance():
    try:
        t = int(time.time() * 1000)
        p = f"timestamp={t}"
        s = sign(p)
        h = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/account?{p}&signature={s}"
        r = requests.get(url, headers=h, timeout=10)
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
        t = int(time.time() * 1000)
        p = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
        s = sign(p)
        h = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{p}&signature={s}"
        r = requests.post(url, headers=h, timeout=10)
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
        t = int(time.time() * 1000)
        p = f"symbol={symbol}&side=SELL&type=MARKET&quantity={qty}&timestamp={t}"
        s = sign(p)
        h = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{p}&signature={s}"
        r = requests.post(url, headers=h, timeout=10)
        return r.status_code == 200
    except:
        return False

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:200]}, timeout=3)
    except:
        pass

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
    
    scores = {"BUY": 0, "SELL": 0}
    
    rsi = calculate_rsi(prices)
    if rsi < RSI_OVERSOLD:
        scores["BUY"] += 40
    elif rsi > RSI_OVERBOUGHT:
        scores["SELL"] += 40
    
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    if sma5 > sma20:
        scores["BUY"] += 20
    elif sma5 < sma20:
        scores["SELL"] += 20
    
    if len(prices) >= 10:
        mom = (prices[-1] - prices[-10]) / prices[-10] * 100
        if mom > 1:
            scores["BUY"] += 15
        elif mom < -1:
            scores["SELL"] += 15
    
    if scores["BUY"] > scores["SELL"] and scores["BUY"] > 25:
        conf = min(90, 55 + scores["BUY"])
        return "BUY", conf, rsi
    elif scores["SELL"] > scores["BUY"] and scores["SELL"] > 25:
        conf = min(90, 55 + scores["SELL"])
        return "SELL", conf, rsi
    else:
        return "HOLD", 0, rsi

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class TradingBot:
    def __init__(self):
        self.positions = []
        self.cooldown = {}
        self.auto_pilot = True
        self.running = True
        
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_profit = 0
        self.consecutive_losses = 0
        self.daily_start = 0
        self.last_reset = datetime.now().date()
        
        self.update_balance()
        self.daily_start = bot_data["balance"]
        
        self.log("🚀 ALL-IN-ONE BOT v1.0 STARTED")
        self.log(f"💰 Balance: ${bot_data['balance']:.2f}")
    
    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        bot_data["logs"].insert(0, {"time": timestamp, "msg": msg})
        if len(bot_data["logs"]) > 100:
            bot_data["logs"].pop()
        print(f"[{timestamp}] {msg}")
    
    def update_balance(self):
        bot_data["balance"] = get_balance()
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_start = bot_data["balance"]
            self.last_reset = today
            self.consecutive_losses = 0
        bot_data["daily_pnl"] = bot_data["balance"] - self.daily_start
        bot_data["drawdown"] = ((self.daily_start - bot_data["balance"]) / self.daily_start * 100) if self.daily_start > 0 else 0
        bot_data["total_profit"] = self.total_profit
        bot_data["total_trades"] = self.total_trades
        bot_data["wins"] = self.wins
        bot_data["losses"] = self.losses
        bot_data["win_rate"] = (self.wins / max(self.total_trades, 1)) * 100
        bot_data["auto_pilot"] = self.auto_pilot
        bot_data["positions"] = self.positions
    
    def get_position(self, symbol):
        for p in self.positions:
            if p["symbol"] == symbol:
                return p
        return None
    
    def scan_market(self):
        signals = []
        for coin in COINS:
            price = get_price(coin)
            if price == 0:
                continue
            signal, conf, rsi = analyze_symbol(coin, price)
            if signal != "HOLD" and conf >= MIN_CONFIDENCE:
                if coin in self.cooldown:
                    if time.time() - self.cooldown[coin] < COOLDOWN_SECONDS:
                        continue
                signals.append({
                    "symbol": coin, "signal": signal, "confidence": conf,
                    "price": price, "rsi": rsi
                })
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        bot_data["signals"] = signals[:20]
        return signals
    
    def can_trade(self):
        daily_loss = self.daily_start - bot_data["balance"]
        if daily_loss > MAX_DAILY_LOSS:
            return False
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False
        if bot_data["balance"] < MIN_BALANCE:
            return False
        return True
    
    def execute_buy(self, s):
        if self.get_position(s["symbol"]) is not None:
            return False
        if len(self.positions) >= MAX_POSITIONS:
            return False
        if not self.can_trade():
            return False
        
        size = min(TRADE_SIZE, bot_data["balance"])
        if size < 5:
            return False
        
        if market_buy(s["symbol"], size):
            bot_data["balance"] -= size
            self.positions.append({
                "symbol": s["symbol"], "entry_price": s["price"], "amount": size,
                "confidence": s["confidence"], "entry_time": time.time(),
                "peak_price": s["price"], "peak_profit": 0
            })
            self.cooldown[s["symbol"]] = time.time()
            self.log(f"✅ BUY {s['symbol']}: ${size:.0f} at ${s['price']:.0f}")
            return True
        return False
    
    def check_positions(self):
        closed = []
        for pos in self.positions[:]:
            price = get_price(pos["symbol"])
            if price == 0:
                continue
            
            profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
            
            if price > pos["peak_price"]:
                pos["peak_price"] = price
                pos["peak_profit"] = profit
            
            if pos["peak_profit"] >= TRAILING_ACTIVATE:
                drop = pos["peak_profit"] - profit
                if drop >= TRAILING_DISTANCE:
                    profit_usdt = pos["amount"] * profit / 100
                    bot_data["balance"] += pos["amount"]
                    self.total_trades += 1
                    self.total_profit += profit_usdt
                    if profit > 0:
                        self.wins += 1
                        self.consecutive_losses = 0
                    else:
                        self.losses += 1
                        self.consecutive_losses += 1
                    self.log(f"🎯 TRAILING STOP {pos['symbol']}: {profit:+.2f}%")
                    closed.append(pos)
                    continue
            
            if profit <= -STOP_LOSS_PCT:
                profit_usdt = pos["amount"] * profit / 100
                bot_data["balance"] += pos["amount"]
                self.total_trades += 1
                self.total_profit += profit_usdt
                if profit > 0:
                    self.wins += 1
                    self.consecutive_losses = 0
                else:
                    self.losses += 1
                    self.consecutive_losses += 1
                self.log(f"🛑 STOP LOSS {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
                continue
        
        for pos in closed:
            self.positions.remove(pos)

# ============================================================================
# FLASK ВЕБ-СЕРВЕР
# ============================================================================

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>TRADING BOT v6.0</title>
    <meta http-equiv="refresh" content="2">
    <style>
        body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
        .card{background:#111;border:1px solid #0f0;border-radius:10px;padding:15px;margin:10px 0}
        .stat{display:flex;justify-content:space-between;padding:5px 0}
        .profit{color:#0f0}.loss{color:#f00}
        .button{background:#0f0;color:#000;border:none;padding:8px 15px;margin:5px;cursor:pointer;border-radius:5px;font-weight:bold}
        .btn-danger{background:#f00;color:#fff}
        .btn-warning{background:#ff0;color:#000}
    </style>
</head>
<body>
<h1>🤖 TRADING BOT v6.0</h1>
<p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>

<div class="card">
    <h2>💰 ПОРТФЕЛЬ</h2>
    <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
    <div class="stat"><span>PNL сегодня:</span><span id="daily_pnl">$0</span></div>
    <div class="stat"><span>Просадка:</span><span id="drawdown">0%</span></div>
</div>

<div class="card">
    <h2>📊 СТАТИСТИКА</h2>
    <div class="stat"><span>Сделок:</span><span id="trades">0</span></div>
    <div class="stat"><span>Винрейт:</span><span id="winrate">0%</span></div>
    <div class="stat"><span>Автопилот:</span><span id="autopilot">ВКЛ</span></div>
</div>

<div class="card">
    <h2>🎮 УПРАВЛЕНИЕ</h2>
    <button class="button btn-warning" onclick="sendCmd('auto')">🤖 АВТОПИЛОТ</button>
    <button class="button btn-danger" onclick="sendCmd('close')">🔒 ЗАКРЫТЬ ВСЁ</button>
    <button class="button" onclick="sendCmd('scan')">🔄 СКАНИРОВАТЬ</button>
    <button class="button" onclick="sendCmd('telegram')">📱 TELEGRAM</button>
</div>

<div class="card">
    <h2>🎯 ТОП СИГНАЛЫ</h2>
    <div id="signals">Загрузка...</div>
</div>

<div class="card">
    <h2>📈 АКТИВНЫЕ ПОЗИЦИИ</h2>
    <div id="positions">Нет</div>
</div>

<div class="card">
    <h2>📋 ЛОГИ</h2>
    <div id="logs" style="height:200px;overflow-y:auto;font-size:11px">Загрузка...</div>
</div>

<script>
async function sendCmd(cmd){await fetch('/cmd/'+cmd);}
async function update(){
    const r=await fetch('/data');
    const d=await r.json();
    document.getElementById('balance').innerHTML='$'+d.balance;
    document.getElementById('daily_pnl').innerHTML=(d.daily_pnl>=0?'+':'')+'$'+d.daily_pnl;
    document.getElementById('drawdown').innerHTML=d.drawdown+'%';
    document.getElementById('trades').innerHTML=d.total_trades;
    document.getElementById('winrate').innerHTML=d.win_rate+'%';
    document.getElementById('autopilot').innerHTML=d.auto_pilot?'✅ ВКЛ':'❌ ВЫКЛ';
    
    let s='';
    for(let sig of d.signals.slice(0,8)){
        s+=`<div class="stat"><span>${sig.symbol}</span><span class="${sig.signal==='BUY'?'profit':'loss'}">${sig.signal}</span><span>${sig.confidence}%</span><span>RSI=${sig.rsi}</span></div>`;
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
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/data')
def data():
    return jsonify({
        "balance": round(bot_data["balance"], 2),
        "daily_pnl": round(bot_data["daily_pnl"], 2),
        "drawdown": round(bot_data["drawdown"], 1),
        "total_trades": bot_data["total_trades"],
        "win_rate": round(bot_data["win_rate"], 1),
        "auto_pilot": bot_data["auto_pilot"],
        "signals": bot_data["signals"],
        "positions": bot_data["positions"],
        "logs": bot_data["logs"]
    })

@app.route('/cmd/<cmd>')
def command(cmd):
    if cmd == 'auto':
        bot.auto_pilot = not bot.auto_pilot
        bot.log(f"🤖 Автопилот: {'ВКЛ' if bot.auto_pilot else 'ВЫКЛ'}")
    elif cmd == 'close':
        for pos in bot.positions[:]:
            market_sell(pos["symbol"], pos["amount"])
        bot.positions = []
        bot.log("🔒 Все позиции закрыты")
    elif cmd == 'scan':
        bot.scan_market()
        bot.log("🔍 Сканирование выполнено")
    elif cmd == 'telegram':
        send_telegram(f"🤖 БОТ АКТИВЕН\nБаланс: ${bot_data['balance']:.2f}")
        bot.log("📱 Telegram уведомление отправлено")
    return "ok"

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = TradingBot()
    
    # Запуск веб-сервера в потоке
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    web_thread.start()
    
    bot.log("🌐 ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    
    # Основной цикл бота
    last_scan = 0
    
    while bot.running:
        try:
            bot.update_balance()
            
            if time.time() - last_scan > 10:
                signals = bot.scan_market()
                last_scan = time.time()
                
                if bot.auto_pilot and signals:
                    for s in signals[:2]:
                        if s["signal"] == "BUY":
                            bot.execute_buy(s)
            
            bot.check_positions()
            
            # Консольный вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            print("=" * 60)
            print("   🤖 ALL-IN-ONE BOT v1.0")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 60)
            print(f"\n   💰 BALANCE: ${bot_data['balance']:.2f}")
            print(f"   📊 PROFIT: ${bot_data['total_profit']:.2f} | WINRATE: {bot_data['win_rate']:.1f}%")
            print(f"   🤖 AUTOPILOT: {'ON' if bot.auto_pilot else 'OFF'}")
            print(f"   📡 TRACKING: {len(COINS)} coins")
            print(f"\n   🎯 TOP SIGNALS:")
            for s in bot_data["signals"][:5]:
                emoji = "📈" if s["signal"] == "BUY" else "📉"
                print(f"      {emoji} {s['symbol']}: {s['signal']} ({s['confidence']}%) | RSI={s['rsi']} | ${s['price']:.0f}")
            print(f"\n   📊 OPEN POSITIONS: {len(bot.positions)}/{MAX_POSITIONS}")
            print("\n" + "=" * 60)
            print("   🌐 Веб-интерфейс: http://localhost:5002")
            print("   💡 Для выхода: Ctrl+C")
            print("=" * 60)
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            bot.running = False
            break
        except Exception as e:
            bot.log(f"Error: {e}")
            time.sleep(5)