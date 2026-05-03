# -*- coding: utf-8 -*-
# ULTIMATE_TRADING_BOT_WORKING.py - ПОЛНОСТЬЮ РАБОЧАЯ ВЕРСИЯ
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

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"
]

TRADE_SIZE = 10
MAX_POSITIONS = 5
MIN_CONFIDENCE = 55
COOLDOWN_SECONDS = 30
POSITION_TIMEOUT = 7200

RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
STOP_LOSS_PCT = 3.5
TAKE_PROFIT_PCT = 7.0
MAX_DAILY_LOSS = 10.0
MAX_CONSECUTIVE_LOSSES = 3

# ============================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ КОМАНД
# ============================================================================

command = None
running = True

# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def sign(params_str):
    return hmac.new(MEXC_API_SECRET.encode(), params_str.encode(), hashlib.sha256).hexdigest()

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

def market_buy(symbol, usdt_amount):
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        quantity = round(usdt_amount / price, 6)
        if quantity < 0.000001:
            return False
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except:
        return False

def market_sell(symbol, usdt_amount):
    try:
        price = get_price(symbol)
        if price == 0:
            return False
        quantity = round(usdt_amount / price, 6)
        if quantity < 0.000001:
            return False
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
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
        return "HOLD", 0, 50, ["No data"]
    
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
        reasons.append("Up trend")
    elif sma5 < sma20:
        scores["SELL"] += 20
        reasons.append("Down trend")
    
    if scores["BUY"] > scores["SELL"] and scores["BUY"] > 25:
        confidence = min(90, 50 + scores["BUY"])
        return "BUY", confidence, rsi, reasons
    elif scores["SELL"] > scores["BUY"] and scores["SELL"] > 25:
        confidence = min(90, 50 + scores["SELL"])
        return "SELL", confidence, rsi, reasons
    else:
        return "HOLD", 0, rsi, ["Stable"]

# ============================================================================
# ФУНКЦИЯ ДЛЯ ВВОДА КОМАНД (В ОТДЕЛЬНОМ ПОТОКЕ)
# ============================================================================

def input_thread():
    global command, running
    while running:
        try:
            cmd = input().strip().lower()
            if cmd:
                command = cmd
        except:
            pass
        time.sleep(0.1)

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class TradingBot:
    def __init__(self):
        self.balance = 0
        self.positions = []
        self.cooldown = {}
        self.auto_pilot = True
        
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_profit = 0
        self.best_trade = 0
        self.worst_trade = 0
        self.consecutive_losses = 0
        self.daily_start = 0
        self.last_reset = datetime.now().date()
        
        self.update_balance()
        self.daily_start = self.balance
        
        self.log("BOT STARTED")
        self.log(f"Balance: ${self.balance:.2f}")
        send_telegram(f"BOT STARTED - Balance: ${self.balance:.2f}")
    
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
    
    def get_position_by_symbol(self, symbol):
        for pos in self.positions:
            if pos["symbol"] == symbol:
                return pos
        return None
    
    def scan_market(self):
        signals = []
        for coin in COINS:
            price = get_price(coin)
            if price == 0:
                continue
            
            signal, confidence, rsi, reasons = analyze_symbol(coin, price)
            
            if signal != "HOLD" and confidence >= MIN_CONFIDENCE:
                if coin in self.cooldown:
                    if time.time() - self.cooldown[coin] < COOLDOWN_SECONDS:
                        continue
                if signal == "BUY" and self.get_position_by_symbol(coin) is not None:
                    continue
                
                signals.append({
                    "symbol": coin,
                    "signal": signal,
                    "confidence": confidence,
                    "price": price,
                    "rsi": rsi,
                    "reasons": reasons
                })
        
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def execute_buy(self, signal):
        if len(self.positions) >= MAX_POSITIONS:
            return False
        
        daily_loss = self.daily_start - self.balance
        if daily_loss > MAX_DAILY_LOSS:
            return False
        
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False
        
        size = min(TRADE_SIZE, self.balance)
        if size < 5:
            return False
        
        success = market_buy(signal["symbol"], size)
        if success:
            self.balance -= size
            self.positions.append({
                "symbol": signal["symbol"],
                "entry_price": signal["price"],
                "amount": size,
                "confidence": signal["confidence"],
                "rsi": signal["rsi"],
                "entry_time": time.time(),
                "stop_loss": signal["price"] * (1 - STOP_LOSS_PCT / 100),
                "take_profit": signal["price"] * (1 + TAKE_PROFIT_PCT / 100)
            })
            self.cooldown[signal["symbol"]] = time.time()
            msg = f"BUY {signal['symbol']}: ${size:.0f} at ${signal['price']:.0f} ({signal['confidence']}%)"
            self.log(msg)
            send_telegram(msg)
            return True
        return False
    
    def execute_sell(self, signal):
        pos = self.get_position_by_symbol(signal["symbol"])
        if pos is None:
            return False
        
        profit_pct = (signal["price"] - pos["entry_price"]) / pos["entry_price"] * 100
        profit_usdt = pos["amount"] * profit_pct / 100
        
        success = market_sell(signal["symbol"], pos["amount"])
        if success:
            self.balance += pos["amount"]
            self.positions.remove(pos)
            self.total_trades += 1
            self.total_profit += profit_usdt
            
            if profit_pct > 0:
                self.wins += 1
                self.consecutive_losses = 0
                if profit_pct > self.best_trade:
                    self.best_trade = profit_pct
            else:
                self.losses += 1
                self.consecutive_losses += 1
                if profit_pct < self.worst_trade:
                    self.worst_trade = profit_pct
            
            msg = f"{'WIN' if profit_pct > 0 else 'LOSS'} SELL {signal['symbol']}: {profit_pct:+.2f}% (${profit_usdt:.2f})"
            self.log(msg)
            send_telegram(msg)
            return True
        return False
    
    def check_positions(self):
        closed = []
        for pos in self.positions[:]:
            price = get_price(pos["symbol"])
            if price == 0:
                continue
            
            profit_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
            pos["current_profit"] = profit_pct
            
            if price <= pos["stop_loss"]:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "stop_loss"
                closed.append(pos)
                self.positions.remove(pos)
            elif price >= pos["take_profit"]:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "take_profit"
                closed.append(pos)
                self.positions.remove(pos)
            elif time.time() - pos["entry_time"] > POSITION_TIMEOUT:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "timeout"
                closed.append(pos)
                self.positions.remove(pos)
        
        for pos in closed:
            profit_usdt = pos["amount"] * pos["profit_pct"] / 100
            self.balance += pos["amount"]
            self.total_trades += 1
            self.total_profit += profit_usdt
            
            if pos["profit_pct"] > 0:
                self.wins += 1
                self.consecutive_losses = 0
            else:
                self.losses += 1
                self.consecutive_losses += 1
            
            self.log(f"{pos['exit_reason']} {pos['symbol']}: {pos['profit_pct']:+.2f}%")
    
    def print_dashboard(self, signals):
        os.system('cls' if os.name == 'nt' else 'clear')
        win_rate = (self.wins / max(self.total_trades, 1)) * 100
        daily_pnl = self.balance - self.daily_start
        
        print("\n" + "=" * 70)
        print("   ULTIMATE TRADING BOT v5.0")
        print("   DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
        print("=" * 70)
        print(f"\n   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\n   BALANCE: ${self.balance:.2f} | PNL TODAY: ${daily_pnl:+.2f}")
        print(f"   TOTAL PROFIT: ${self.total_profit:.2f} | WINRATE: {win_rate:.1f}%")
        print(f"   TRADES: {self.total_trades} (W:{self.wins} L:{self.losses})")
        print(f"   BEST: +{self.best_trade:.1f}% | WORST: {self.worst_trade:.1f}%")
        print(f"   AUTOPILOT: {'ON' if self.auto_pilot else 'OFF'}")
        
        print(f"\n   TOP SIGNALS:")
        for i, sig in enumerate(signals[:8]):
            emoji = "UP" if sig["signal"] == "BUY" else "DOWN"
            print(f"      {i+1}. {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | RSI={sig['rsi']:.0f} | ${sig['price']:.0f}")
        
        print(f"\n   OPEN POSITIONS: {len(self.positions)}/{MAX_POSITIONS}")
        for pos in self.positions:
            profit = pos.get("current_profit", 0)
            status = "UP" if profit > 0 else "DOWN" if profit < 0 else "IDLE"
            print(f"      {status} {pos['symbol']}: {profit:+.1f}% | ${pos['amount']:.0f}")
        
        print("\n" + "=" * 70)
        print("   COMMANDS (type and press Enter):")
        print("      a - Autopilot     s - Status     c - Close all")
        print("      r - Rescan        t - Telegram   q - Quit")
        print("=" * 70)
    
    def run(self):
        global command, running
        
        # Запускаем поток для ввода команд
        t = threading.Thread(target=input_thread, daemon=True)
        t.start()
        
        last_scan = 0
        signals = []
        
        while running:
            try:
                self.update_balance()
                
                if time.time() - last_scan > 10:
                    signals = self.scan_market()
                    last_scan = time.time()
                
                if self.auto_pilot and signals:
                    opened = 0
                    for sig in signals:
                        if opened >= 2:
                            break
                        if sig["signal"] == "BUY":
                            if self.execute_buy(sig):
                                opened += 1
                        elif sig["signal"] == "SELL":
                            if self.execute_sell(sig):
                                opened += 1
                
                self.check_positions()
                self.print_dashboard(signals)
                
                # Обработка команд из потока
                if command is not None:
                    cmd = command
                    command = None
                    
                    if cmd == 'a':
                        self.auto_pilot = not self.auto_pilot
                        self.log(f"Autopilot: {'ON' if self.auto_pilot else 'OFF'}")
                    elif cmd == 's':
                        self.log(f"Balance: ${self.balance:.2f}, Profit: ${self.total_profit:.2f}")
                        send_telegram(f"Balance: ${self.balance:.2f}, Profit: ${self.total_profit:.2f}")
                    elif cmd == 'c':
                        for pos in self.positions[:]:
                            price = get_price(pos["symbol"])
                            if price > 0:
                                market_sell(pos["symbol"], pos["amount"])
                        self.positions = []
                        self.log("All positions closed")
                        send_telegram("All positions closed")
                    elif cmd == 'r':
                        signals = self.scan_market()
                        self.log("Market rescanned")
                    elif cmd == 't':
                        send_telegram("Test message from bot")
                        self.log("Telegram test sent")
                    elif cmd == 'q':
                        running = False
                        self.log("Bot stopped")
                        send_telegram("Bot stopped")
                        break
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                running = False
                self.log("Bot stopped by user")
                break
            except Exception as e:
                self.log(f"Error: {e}")
                time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()