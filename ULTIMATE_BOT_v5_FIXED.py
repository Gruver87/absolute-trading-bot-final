# -*- coding: utf-8 -*-
# ULTIMATE_BOT_v5_FIXED.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import threading
from datetime import datetime

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

PAPER_MODE = False  # False = реальная торговля
PAPER_BALANCE = 10000

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# ТОРГУЕМЫЕ МОНЕТЫ (ФИКСИРОВАННЫЙ СПИСОК - 100% РАБОТАЕТ)
# ============================================================================

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT",
    "ATOMUSDT", "LTCUSDT", "ETCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "FILUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "PYTHUSDT",
    "JUPUSDT", "WIFUSDT", "BONKUSDT", "PEPEUSDT", "FLOKIUSDT", "SHIBUSDT",
    "TONUSDT", "TRXUSDT", "XLMUSDT", "VETUSDT", "HBARUSDT", "ICPUSDT",
    "EGLDUSDT", "THETAUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT", "AXSUSDT",
    "RNDRUSDT", "IMXUSDT", "STXUSDT", "MKRUSDT", "CRVUSDT", "SNXUSDT",
    "COMPUSDT", "ZECUSDT", "DASHUSDT", "XMRUSDT", "EOSUSDT", "XTZUSDT",
    "KSMUSDT", "WAVESUSDT", "ALGOUSDT", "FLOWUSDT", "MINAUSDT", "CFXUSDT",
    "APEUSDT", "LDOUSDT", "RPLUSDT", "FXSUSDT", "GMXUSDT", "RDNTUSDT"
]

print(f"📊 Загружено торговых пар: {len(COINS)}")

# ============================================================================
# НАСТРОЙКИ ТОРГОВЛИ
# ============================================================================

TRADE_SIZE = 10
MAX_POSITIONS = 5
MIN_CONFIDENCE = 55
COOLDOWN_SECONDS = 30
POSITION_TIMEOUT = 7200

RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
STOP_LOSS_PCT = 3.5

TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0

MAX_DAILY_LOSS = 15.0
MAX_CONSECUTIVE_LOSSES = 5
MIN_BALANCE = 20

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
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:300]}, timeout=3)
    except:
        pass

# ============================================================================
# ТЕХНИЧЕСКИЙ АНАЛИЗ
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
        return "HOLD", 0, 50, ["Нет данных"]
    
    scores = {"BUY": 0, "SELL": 0}
    reasons = []
    
    rsi = calculate_rsi(prices)
    if rsi < RSI_OVERSOLD:
        scores["BUY"] += 40
        reasons.append(f"RSI={rsi:.0f} oversold")
    elif rsi > RSI_OVERBOUGHT:
        scores["SELL"] += 40
        reasons.append(f"RSI={rsi:.0f} overbought")
    
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    if sma5 > sma20:
        scores["BUY"] += 20
        reasons.append("Uptrend")
    elif sma5 < sma20:
        scores["SELL"] += 20
        reasons.append("Downtrend")
    
    if len(prices) >= 10:
        mom = (prices[-1] - prices[-10]) / prices[-10] * 100
        if mom > 1:
            scores["BUY"] += 15
            reasons.append(f"Momentum +{mom:.1f}%")
        elif mom < -1:
            scores["SELL"] += 15
            reasons.append(f"Momentum {mom:.1f}%")
    
    if scores["BUY"] > scores["SELL"] and scores["BUY"] > 25:
        conf = min(90, 55 + scores["BUY"])
        return "BUY", conf, rsi, reasons[:3]
    elif scores["SELL"] > scores["BUY"] and scores["SELL"] > 25:
        conf = min(90, 55 + scores["SELL"])
        return "SELL", conf, rsi, reasons[:3]
    else:
        return "HOLD", 0, rsi, ["Market stable"]

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class TradingBot:
    def __init__(self):
        self.balance = 0
        self.positions = []
        self.cooldown = {}
        self.auto_pilot = True
        self.running = True
        self.command = None
        
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_profit = 0
        self.consecutive_losses = 0
        self.daily_start = 0
        self.last_reset = datetime.now().date()
        
        self.update_balance()
        self.daily_start = self.balance
        
        mode = "REAL" if not PAPER_MODE else "PAPER"
        self.log(f"🚀 ULTIMATE BOT v5.0 STARTED [{mode} MODE]")
        self.log(f"💰 Balance: ${self.balance:.2f}")
        self.log(f"📊 Tracking: {len(COINS)} coins")
        self.log(f"⚡ Strategy: Trailing stop (activate +{TRAILING_ACTIVATE}%, drop {TRAILING_DISTANCE}%)")
        send_telegram(f"🚀 BOT STARTED [{mode}]\n💰 Balance: ${self.balance:.2f}")
    
    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")
    
    def update_balance(self):
        self.balance = get_balance()
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_start = self.balance
            self.last_reset = today
            self.consecutive_losses = 0
    
    def get_position(self, symbol):
        for p in self.positions:
            if p["symbol"] == symbol:
                return p
        return None
    
    def scan_market(self):
        signals = []
        for coin in COINS[:100]:
            price = get_price(coin)
            if price == 0:
                continue
            
            signal, conf, rsi, reasons = analyze_symbol(coin, price)
            
            if signal != "HOLD" and conf >= MIN_CONFIDENCE:
                if coin in self.cooldown:
                    if time.time() - self.cooldown[coin] < COOLDOWN_SECONDS:
                        continue
                if signal == "BUY" and self.get_position(coin):
                    continue
                
                signals.append({
                    "symbol": coin, "signal": signal, "confidence": conf,
                    "price": price, "rsi": rsi, "reasons": reasons
                })
        
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def can_trade(self):
        daily_loss = self.daily_start - self.balance
        if daily_loss > MAX_DAILY_LOSS:
            return False
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False
        if self.balance < MIN_BALANCE:
            return False
        return True
    
    def execute_buy(self, s):
        if len(self.positions) >= MAX_POSITIONS:
            return False
        if not self.can_trade():
            return False
        
        size = min(TRADE_SIZE, self.balance)
        if size < 5:
            return False
        
        if market_buy(s["symbol"], size):
            self.balance -= size
            self.positions.append({
                "symbol": s["symbol"],
                "entry_price": s["price"],
                "amount": size,
                "confidence": s["confidence"],
                "entry_time": time.time(),
                "peak_price": s["price"],
                "peak_profit": 0
            })
            self.cooldown[s["symbol"]] = time.time()
            self.log(f"✅ BUY {s['symbol']}: ${size:.0f} at ${s['price']:.0f} ({s['confidence']}%)")
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
            
            # Трейлинг-стоп
            if pos["peak_profit"] >= TRAILING_ACTIVATE:
                drop = pos["peak_profit"] - profit
                if drop >= TRAILING_DISTANCE:
                    profit_usdt = pos["amount"] * profit / 100
                    self.balance += pos["amount"]
                    self.total_trades += 1
                    self.total_profit += profit_usdt
                    
                    if profit > 0:
                        self.wins += 1
                        self.consecutive_losses = 0
                    else:
                        self.losses += 1
                        self.consecutive_losses += 1
                    
                    self.log(f"🎉 TRAILING STOP {pos['symbol']}: {profit:+.2f}% (peak: +{pos['peak_profit']:.1f}%)")
                    closed.append(pos)
                    continue
            
            # Стоп-лосс
            if profit <= -STOP_LOSS_PCT:
                profit_usdt = pos["amount"] * profit / 100
                self.balance += pos["amount"]
                self.total_trades += 1
                self.total_profit += profit_usdt
                
                if profit > 0:
                    self.wins += 1
                    self.consecutive_losses = 0
                else:
                    self.losses += 1
                    self.consecutive_losses += 1
                
                self.log(f"🛑 STOP-LOSS {pos['symbol']}: {profit:+.2f}%")
                closed.append(pos)
                continue
        
        for pos in closed:
            self.positions.remove(pos)
    
    def print_dashboard(self, signals):
        os.system('cls' if os.name == 'nt' else 'clear')
        win_rate = (self.wins / max(self.total_trades, 1)) * 100
        daily_pnl = self.balance - self.daily_start
        mode = "REAL" if not PAPER_MODE else "PAPER"
        
        print("\n" + "=" * 80)
        print(f"   🚀 ULTIMATE BOT v5.0 - [{mode} MODE]")
        print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
        print("=" * 80)
        print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\n   💰 BALANCE: ${self.balance:.2f} | DAILY PNL: ${daily_pnl:+.2f}")
        print(f"   📊 TOTAL PROFIT: ${self.total_profit:.2f} | WINRATE: {win_rate:.1f}%")
        print(f"   🏆 TRADES: {self.total_trades} (W:{self.wins} L:{self.losses})")
        print(f"   🤖 AUTOPILOT: {'✅ ON' if self.auto_pilot else '❌ OFF'}")
        print(f"   📡 TRACKING: {len(COINS)} coins")
        print(f"   ⚡ STRATEGY: Trailing stop (activate +{TRAILING_ACTIVATE}%, drop {TRAILING_DISTANCE}%)")
        
        print(f"\n   🎯 TOP SIGNALS:")
        for i, s in enumerate(signals[:8]):
            emoji = "📈" if s["signal"] == "BUY" else "📉"
            print(f"      {i+1}. {emoji} {s['symbol']}: {s['signal']} ({s['confidence']}%) | RSI={s['rsi']:.0f} | ${s['price']:.0f}")
        
        print(f"\n   📊 OPEN POSITIONS: {len(self.positions)}/{MAX_POSITIONS}")
        for pos in self.positions:
            price = get_price(pos["symbol"])
            if price > 0:
                profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
                status = "📈" if profit > 0 else "📉" if profit < 0 else "⏸️"
                print(f"      {status} {pos['symbol']}: {profit:+.2f}% (peak: +{pos.get('peak_profit', 0):.1f}%)")
        
        print("\n" + "=" * 80)
        print("   🎮 COMMANDS (type and press Enter):")
        print("      a - Autopilot     s - Status        c - Close all")
        print("      r - Rescan        t - Telegram      q - Quit")
        print("=" * 80)
    
    def input_handler(self):
        while self.running:
            try:
                cmd = input().strip().lower()
                if cmd:
                    self.command = cmd
                time.sleep(0.1)
            except:
                pass
    
    def run(self):
        threading.Thread(target=self.input_handler, daemon=True).start()
        signals = []
        last_scan = 0
        
        while self.running:
            try:
                self.update_balance()
                
                if time.time() - last_scan > 10:
                    signals = self.scan_market()
                    last_scan = time.time()
                
                if self.auto_pilot and signals:
                    opened = 0
                    for s in signals:
                        if opened >= 2:
                            break
                        if s["signal"] == "BUY":
                            if self.execute_buy(s):
                                opened += 1
                
                self.check_positions()
                self.print_dashboard(signals)
                
                if self.command:
                    cmd = self.command
                    self.command = None
                    
                    if cmd == 'a':
                        self.auto_pilot = not self.auto_pilot
                        self.log(f"Autopilot: {'ON' if self.auto_pilot else 'OFF'}")
                    elif cmd == 's':
                        self.log(f"Balance: ${self.balance:.2f}, Profit: ${self.total_profit:.2f}")
                    elif cmd == 'c':
                        for pos in self.positions[:]:
                            market_sell(pos["symbol"], pos["amount"])
                        self.positions = []
                        self.log("All positions closed")
                    elif cmd == 'r':
                        signals = self.scan_market()
                        self.log("Market rescanned")
                    elif cmd == 't':
                        send_telegram(f"Bot alive! Balance: ${self.balance:.2f}")
                        self.log("Telegram test sent")
                    elif cmd == 'q':
                        self.running = False
                        self.log("Bot stopped")
                        break
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                self.log(f"Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()