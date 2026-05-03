# -*- coding: utf-8 -*-
# full_trade_bot.py - ПОЛНАЯ ТОРГОВЛЯ SPOT + FUTURES
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
import msvcrt
import json
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

# Монеты для торговли (с большим объёмом)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

# Размеры позиций
SPOT_TRADE_SIZE = 5      # $5 на спот сделку
FUTURES_TRADE_SIZE = 5   # $5 на фьючерс сделку
FUTURES_LEVERAGE = 3     # Плечо 3x (безопасно)

# Риск-менеджмент
STOP_LOSS_PCT = 2.0      # Стоп-лосс 2%
TAKE_PROFIT_PCT = 4.0    # Тейк-профит 4%

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
# БАЛАНСЫ
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
        log_print(f"?? Ошибка спот баланса: {e}")
    return 0

def get_futures_balance():
    """Получить фьючерс баланс USDT"""
    try:
        timestamp = int(time.time() * 1000)
        params = f"timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/futures/account?{params}&signature={signature}"
        
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return float(data.get("free", 0))
    except Exception as e:
        log_print(f"?? Ошибка фьючерс баланса: {e}")
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

def get_all_prices():
    """Получить цены всех монет"""
    prices = {}
    for coin in COINS:
        price = get_price(coin)
        if price > 0:
            prices[coin] = price
    return prices

def analyze_symbol(symbol, price):
    """Анализ монеты с RSI"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30", timeout=5)
        if r.status_code == 200:
            candles = r.json()
            prices = [float(c[4]) for c in candles]
            
            if len(prices) > 14:
                # Вычисляем RSI
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
                
                # Сигналы
                if rsi < 35:
                    confidence = int(65 + (35 - rsi))
                    return "BUY", min(90, confidence), round(rsi, 1)
                elif rsi > 65:
                    confidence = int(65 + (rsi - 65))
                    return "SELL", min(90, confidence), round(rsi, 1)
    except:
        pass
    
    return "HOLD", 50, 50

# ============================================================================
# СПОТ ТОРГОВЛЯ
# ============================================================================

def spot_buy(symbol, usdt_amount):
    """Покупка на споте"""
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

def spot_sell(symbol, usdt_amount):
    """Продажа на споте"""
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
# ФЬЮЧЕРС ТОРГОВЛЯ
# ============================================================================

def set_futures_leverage(symbol, leverage):
    """Установить плечо для фьючерсов"""
    try:
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&leverage={leverage}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/futures/leverage?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except:
        return False

def futures_open_long(symbol, usdt_amount, leverage):
    """Открыть LONG позицию (шорт)"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False, "No price"
        
        quantity = round((usdt_amount * leverage) / price, 6)
        if quantity < 0.000001:
            return False, "Quantity too small"
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/futures/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return True, f"LONG {quantity} {symbol} (x{leverage})"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def futures_open_short(symbol, usdt_amount, leverage):
    """Открыть SHORT позицию"""
    try:
        price = get_price(symbol)
        if price == 0:
            return False, "No price"
        
        quantity = round((usdt_amount * leverage) / price, 6)
        if quantity < 0.000001:
            return False, "Quantity too small"
        
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/futures/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return True, f"SHORT {quantity} {symbol} (x{leverage})"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class FullTradingBot:
    def __init__(self):
        self.spot_balance = 0
        self.futures_balance = 0
        self.spot_positions = []
        self.futures_positions = []
        self.auto_pilot = True
        self.consecutive_losses = 0
        self.total_trades = 0
        self.winning_trades = 0
        
        self.update_balances()
        log_print("?? FULL TRADING BOT ЗАПУЩЕН (SPOT + FUTURES)")
        log_print(f"?? Спот баланс: ${self.spot_balance:.2f}")
        log_print(f"?? Фьючерс баланс: ${self.futures_balance:.2f}")
    
    def update_balances(self):
        self.spot_balance = get_spot_balance()
        self.futures_balance = get_futures_balance()
    
    def scan_market(self):
        """Сканирование рынка для всех монет"""
        signals = []
        for coin in COINS:
            price = get_price(coin)
            if price == 0:
                continue
            signal, confidence, rsi = analyze_symbol(coin, price)
            if signal != "HOLD" and confidence > 65:
                signals.append({
                    "symbol": coin,
                    "signal": signal,
                    "confidence": confidence,
                    "price": price,
                    "rsi": rsi
                })
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def execute_spot_trade(self, signal):
        """Исполнение спот сделки"""
        if signal["signal"] == "BUY":
            if self.spot_balance >= SPOT_TRADE_SIZE:
                success, msg = spot_buy(signal["symbol"], SPOT_TRADE_SIZE)
                if success:
                    self.spot_balance -= SPOT_TRADE_SIZE
                    self.spot_positions.append({
                        "symbol": signal["symbol"],
                        "entry_price": signal["price"],
                        "amount": SPOT_TRADE_SIZE,
                        "time": time.time()
                    })
                    log_print(f"? SPOT BUY {signal['symbol']}: ${SPOT_TRADE_SIZE} по {signal['price']:.0f}")
                    return True
        else:
            # Ищем позицию для продажи
            for pos in self.spot_positions[:]:
                if pos["symbol"] == signal["symbol"]:
                    success, msg = spot_sell(signal["symbol"], SPOT_TRADE_SIZE)
                    if success:
                        profit_pct = (signal["price"] - pos["entry_price"]) / pos["entry_price"] * 100
                        self.spot_balance += SPOT_TRADE_SIZE
                        self.spot_positions.remove(pos)
                        self.total_trades += 1
                        if profit_pct > 0:
                            self.winning_trades += 1
                        log_print(f"? SPOT SELL {signal['symbol']}: {profit_pct:+.2f}%")
                        return True
        return False
    
    def execute_futures_trade(self, signal):
        """Исполнение фьючерс сделки"""
        if self.futures_balance < FUTURES_TRADE_SIZE:
            return False
        
        # Устанавливаем плечо
        set_futures_leverage(signal["symbol"], FUTURES_LEVERAGE)
        
        if signal["signal"] == "BUY":
            success, msg = futures_open_long(signal["symbol"], FUTURES_TRADE_SIZE, FUTURES_LEVERAGE)
            if success:
                self.futures_balance -= FUTURES_TRADE_SIZE
                self.futures_positions.append({
                    "symbol": signal["symbol"],
                    "side": "LONG",
                    "entry_price": signal["price"],
                    "amount": FUTURES_TRADE_SIZE,
                    "leverage": FUTURES_LEVERAGE,
                    "time": time.time()
                })
                log_print(f"? FUTURES LONG {signal['symbol']}: ${FUTURES_TRADE_SIZE} (x{FUTURES_LEVERAGE})")
                return True
        else:
            success, msg = futures_open_short(signal["symbol"], FUTURES_TRADE_SIZE, FUTURES_LEVERAGE)
            if success:
                self.futures_balance -= FUTURES_TRADE_SIZE
                self.futures_positions.append({
                    "symbol": signal["symbol"],
                    "side": "SHORT",
                    "entry_price": signal["price"],
                    "amount": FUTURES_TRADE_SIZE,
                    "leverage": FUTURES_LEVERAGE,
                    "time": time.time()
                })
                log_print(f"? FUTURES SHORT {signal['symbol']}: ${FUTURES_TRADE_SIZE} (x{FUTURES_LEVERAGE})")
                return True
        return False
    
    def run(self):
        log_print("?? Начинаю анализ рынка...")
        
        while True:
            try:
                self.update_balances()
                signals = self.scan_market()
                
                # Автопилот
                if self.auto_pilot and signals:
                    for sig in signals[:3]:  # Максимум 3 сделки за цикл
                        # Спот сделки
                        if self.spot_balance >= SPOT_TRADE_SIZE:
                            self.execute_spot_trade(sig)
                        
                        # Фьючерс сделки
                        if self.futures_balance >= FUTURES_TRADE_SIZE:
                            self.execute_futures_trade(sig)
                
                # Очистка старых позиций (таймаут 1 час)
                now = time.time()
                self.spot_positions = [p for p in self.spot_positions if now - p["time"] < 3600]
                self.futures_positions = [p for p in self.futures_positions if now - p["time"] < 3600]
                
                # Вывод в консоль
                os.system('cls' if os.name == 'nt' else 'clear')
                win_rate = (self.winning_trades / max(self.total_trades, 1)) * 100
                
                print("\n" + "=" * 70)
                print("   ?? FULL TRADING BOT - MEXC (SPOT + FUTURES)")
                print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
                print("=" * 70)
                print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"\n   ?? СПОТ БАЛАНС: ${self.spot_balance:.2f}")
                print(f"   ? ФЬЮЧЕРС БАЛАНС: ${self.futures_balance:.2f}")
                print(f"   ?? ВИНРЕЙТ: {win_rate:.0f}% | СДЕЛОК: {self.total_trades}")
                print(f"   ?? АВТОПИЛОТ: {'? ВКЛ' if self.auto_pilot else '? ВЫКЛ'}")
                
                print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
                for sig in signals[:5]:
                    emoji = "??" if sig["signal"] == "BUY" else "??"
                    print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | RSI={sig['rsi']} | ${sig['price']:.0f}")
                
                print(f"\n   ?? АКТИВНЫХ ПОЗИЦИЙ: СПОТ={len(self.spot_positions)} | ФЬЮЧЕРС={len(self.futures_positions)}")
                
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
                        log_print(f"?? Спот: ${self.spot_balance:.2f}, Фьючерс: ${self.futures_balance:.2f}, Сделок: {self.total_trades}")
                    elif key == 'q':
                        log_print("?? Бот остановлен")
                        break
                
                time.sleep(15)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                log_print(f"?? Ошибка: {e}")
                time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = FullTradingBot()
    bot.run()