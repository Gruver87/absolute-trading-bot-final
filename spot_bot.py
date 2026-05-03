# -*- coding: utf-8 -*-
# spot_bot.py - ТОРГОВЛЯ ТОЛЬКО НА СПОТЕ MEXC
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import msvcrt
from datetime import datetime

# ============================================================================
# ТВОИ API КЛЮЧИ
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# НАСТРОЙКИ ТОРГОВЛИ
# ============================================================================

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
TRADE_SIZE = 5          # $5 на сделку
MIN_BALANCE = 10        # Минимальный баланс для торговли
MAX_POSITIONS = 3       # Максимум открытых позиций

# ============================================================================
# MEXC API ФУНКЦИИ
# ============================================================================

def sign(params_str):
    return hmac.new(MEXC_API_SECRET.encode(), params_str.encode(), hashlib.sha256).hexdigest()

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:400]}, timeout=3)
    except:
        pass

def log_print(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")
    send_telegram(msg)

# ============================================================================
# БАЛАНС
# ============================================================================

def get_spot_balance():
    """Получить спот баланс USDT"""
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
    except Exception as e:
        log_print(f"?? Ошибка баланса: {e}")
    return 0

# ============================================================================
# ЦЕНЫ И АНАЛИЗ
# ============================================================================

def get_price(symbol):
    """Получить текущую цену"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def analyze_symbol(symbol, price):
    """Анализ монеты с RSI"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30", timeout=5)
        if r.status_code == 200:
            candles = r.json()
            prices = [float(c[4]) for c in candles]
            
            if len(prices) > 14:
                gains, losses = [], []
                for i in range(1, len(prices[-15:])):
                    diff = prices[-i] - prices[-i-1]
                    if diff > 0:
                        gains.append(diff)
                    else:
                        losses.append(abs(diff))
                
                avg_gain = sum(gains) / 14 if gains else 0
                avg_loss = sum(losses) / 14 if losses else 0.001
                rsi = 100 - (100 / (1 + avg_gain / avg_loss))
                
                if rsi < 35:
                    confidence = int(65 + (35 - rsi))
                    return "BUY", min(90, confidence), round(rsi, 1)
                elif rsi > 65:
                    confidence = int(65 + (rsi - 65))
                    return "SELL", min(90, confidence), round(rsi, 1)
    except:
        pass
    
    return "HOLD", 50, 50

def get_all_signals():
    """Получить сигналы для всех монет"""
    signals = []
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        signal, confidence, rsi = analyze_symbol(coin, price)
        if signal != "HOLD" and confidence > 60:
            signals.append({
                "symbol": coin,
                "signal": signal,
                "confidence": confidence,
                "price": price,
                "rsi": rsi
            })
    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals

# ============================================================================
# СПОТ ТОРГОВЛЯ
# ============================================================================

def spot_market_buy(symbol, usdt_amount):
    """Рыночная покупка"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False, "No price"
        
        quantity = round(usdt_amount / price, 6)
        if quantity < 0.000001:
            return False, "Quantity too small"
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return True, f"Куплено {quantity} {symbol}"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def spot_market_sell(symbol, usdt_amount):
    """Рыночная продажа"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False, "No price"
        
        quantity = round(usdt_amount / price, 6)
        if quantity < 0.000001:
            return False, "Quantity too small"
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return True, f"Продано {quantity} {symbol}"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class SpotBot:
    def __init__(self):
        self.balance = 0
        self.positions = []
        self.auto_pilot = True
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0
        
        self.update_balance()
        log_print("?? SPOT БОТ ЗАПУЩЕН")
        log_print(f"?? Спот баланс: ${self.balance:.2f}")
    
    def update_balance(self):
        self.balance = get_spot_balance()
    
    def execute_trade(self, signal):
        """Исполнение сделки"""
        if signal["signal"] == "BUY":
            if self.balance >= TRADE_SIZE and len(self.positions) < MAX_POSITIONS:
                success, msg = spot_market_buy(signal["symbol"], TRADE_SIZE)
                if success:
                    self.balance -= TRADE_SIZE
                    self.positions.append({
                        "symbol": signal["symbol"],
                        "entry_price": signal["price"],
                        "amount": TRADE_SIZE,
                        "time": time.time()
                    })
                    log_print(f"? ПОКУПКА {signal['symbol']}: ${TRADE_SIZE} по {signal['price']:.0f}")
                    return True
        else:
            # Ищем позицию для продажи
            for pos in self.positions[:]:
                if pos["symbol"] == signal["symbol"]:
                    success, msg = spot_market_sell(signal["symbol"], TRADE_SIZE)
                    if success:
                        profit_pct = (signal["price"] - pos["entry_price"]) / pos["entry_price"] * 100
                        profit_usdt = TRADE_SIZE * profit_pct / 100
                        self.balance += TRADE_SIZE
                        self.positions.remove(pos)
                        self.total_trades += 1
                        self.total_profit += profit_usdt
                        if profit_pct > 0:
                            self.winning_trades += 1
                        emoji = "??" if profit_pct > 0 else "??"
                        log_print(f"{emoji} ПРОДАЖА {signal['symbol']}: {profit_pct:+.2f}% (+${profit_usdt:.2f})")
                        return True
        return False
    
    def run(self):
        log_print("?? Начинаю анализ рынка...")
        
        while True:
            try:
                self.update_balance()
                signals = get_all_signals()
                
                # Автопилот
                if self.auto_pilot and signals:
                    for sig in signals[:2]:
                        self.execute_trade(sig)
                
                # Очистка старых позиций (таймаут 2 часа)
                now = time.time()
                self.positions = [p for p in self.positions if now - p["time"] < 7200]
                
                # Вывод в консоль
                os.system('cls' if os.name == 'nt' else 'clear')
                win_rate = (self.winning_trades / max(self.total_trades, 1)) * 100
                
                print("\n" + "=" * 70)
                print("   ?? SPOT TRADING BOT - MEXC")
                print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
                print("=" * 70)
                print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"\n   ?? БАЛАНС: ${self.balance:.2f}")
                print(f"   ?? ПРИБЫЛЬ: ${self.total_profit:.2f}")
                print(f"   ?? ВИНРЕЙТ: {win_rate:.0f}% | СДЕЛОК: {self.total_trades}")
                print(f"   ?? АВТОПИЛОТ: {'? ВКЛ' if self.auto_pilot else '? ВЫКЛ'}")
                
                print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
                for sig in signals[:5]:
                    emoji = "??" if sig["signal"] == "BUY" else "??"
                    print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | RSI={sig['rsi']} | ${sig['price']:.0f}")
                
                print(f"\n   ?? АКТИВНЫХ ПОЗИЦИЙ: {len(self.positions)}")
                
                print("\n" + "=" * 70)
                print("   ?? КОМАНДЫ: [A] Автопилот  [S] Статус  [Q] Выход")
                print("=" * 70)
                
                # Клавиши
                if msvcrt.kbhit():
                    key = msvcrt.getch().decode('ascii').lower()
                    if key == 'a':
                        self.auto_pilot = not self.auto_pilot
                        log_print(f"?? Автопилот: {'ВКЛ' if self.auto_pilot else 'ВЫКЛ'}")
                    elif key == 's':
                        log_print(f"?? Баланс: ${self.balance:.2f}, Прибыль: ${self.total_profit:.2f}, Сделок: {self.total_trades}")
                    elif key == 'q':
                        log_print("?? Бот остановлен")
                        break
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                log_print(f"?? Ошибка: {e}")
                time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = SpotBot()
    bot.run()