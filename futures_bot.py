# -*- coding: utf-8 -*-
# futures_bot.py - ТОРГОВЛЯ ТОЛЬКО НА ФЬЮЧЕРСАХ MEXC
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
LEVERAGE = 3            # Плечо 3x (1x, 2x, 3x, 5x, 10x)
MIN_BALANCE = 10        # Минимальный баланс для торговли
MAX_POSITIONS = 3       # Максимум открытых позиций

# Риск-менеджмент
STOP_LOSS_PCT = 2.0     # Стоп-лосс 2%
TAKE_PROFIT_PCT = 4.0   # Тейк-профит 4%

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
    """Анализ монеты с RSI и MACD"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30", timeout=5)
        if r.status_code == 200:
            candles = r.json()
            prices = [float(c[4]) for c in candles]
            
            if len(prices) > 14:
                # RSI
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
                
                # SMA для тренда
                sma5 = sum(prices[-5:]) / 5
                sma20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else sma5
                
                # Сигналы для фьючерсов (LONG/SHORT)
                if rsi < 35 and sma5 > sma20:
                    confidence = int(65 + (35 - rsi))
                    return "LONG", min(90, confidence), round(rsi, 1)
                elif rsi > 65 and sma5 < sma20:
                    confidence = int(65 + (rsi - 65))
                    return "SHORT", min(90, confidence), round(rsi, 1)
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
# ФЬЮЧЕРС ТОРГОВЛЯ
# ============================================================================

def set_leverage(symbol, leverage):
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
    """Открыть LONG позицию (ставка на рост)"""
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
    """Открыть SHORT позицию (ставка на падение)"""
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

def close_futures_position(symbol, quantity, side):
    """Закрыть фьючерс позицию"""
    try:
        close_side = "SELL" if side == "BUY" else "BUY"
        timestamp = int(time.time() * 1000)
        params = f"symbol={symbol}&side={close_side}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
        signature = sign(params)
        headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
        url = f"https://api.mexc.com/api/v3/futures/order?{params}&signature={signature}"
        
        r = requests.post(url, headers=headers, timeout=10)
        return r.status_code == 200
    except:
        return False

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class FuturesBot:
    def __init__(self):
        self.balance = 0
        self.positions = []
        self.auto_pilot = True
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0
        
        self.update_balance()
        log_print("? FUTURES БОТ ЗАПУЩЕН")
        log_print(f"?? Фьючерс баланс: ${self.balance:.2f}")
        log_print(f"? Плечо: {LEVERAGE}x")
    
    def update_balance(self):
        self.balance = get_futures_balance()
    
    def execute_trade(self, signal):
        """Исполнение фьючерс сделки"""
        if self.balance < TRADE_SIZE:
            return False
        
        if len(self.positions) >= MAX_POSITIONS:
            return False
        
        # Устанавливаем плечо
        set_leverage(signal["symbol"], LEVERAGE)
        
        if signal["signal"] == "LONG":
            success, msg = futures_open_long(signal["symbol"], TRADE_SIZE, LEVERAGE)
            if success:
                self.balance -= TRADE_SIZE
                self.positions.append({
                    "symbol": signal["symbol"],
                    "side": "LONG",
                    "entry_price": signal["price"],
                    "amount": TRADE_SIZE,
                    "leverage": LEVERAGE,
                    "time": time.time()
                })
                log_print(f"? LONG {signal['symbol']}: ${TRADE_SIZE} (x{LEVERAGE}) по {signal['price']:.0f}")
                return True
        
        elif signal["signal"] == "SHORT":
            success, msg = futures_open_short(signal["symbol"], TRADE_SIZE, LEVERAGE)
            if success:
                self.balance -= TRADE_SIZE
                self.positions.append({
                    "symbol": signal["symbol"],
                    "side": "SHORT",
                    "entry_price": signal["price"],
                    "amount": TRADE_SIZE,
                    "leverage": LEVERAGE,
                    "time": time.time()
                })
                log_print(f"? SHORT {signal['symbol']}: ${TRADE_SIZE} (x{LEVERAGE}) по {signal['price']:.0f}")
                return True
        
        return False
    
    def check_positions(self, current_prices):
        """Проверка открытых позиций (стоп-лосс, тейк-профит)"""
        closed = []
        
        for pos in self.positions[:]:
            current_price = current_prices.get(pos["symbol"], 0)
            if current_price == 0:
                continue
            
            if pos["side"] == "LONG":
                profit_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100 * pos["leverage"]
            else:
                profit_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100 * pos["leverage"]
            
            # Проверка стоп-лосса
            if profit_pct <= -STOP_LOSS_PCT:
                # Закрываем позицию
                quantity = round((pos["amount"] * pos["leverage"]) / pos["entry_price"], 6)
                close_futures_position(pos["symbol"], quantity, "BUY" if pos["side"] == "LONG" else "SELL")
                self.balance += pos["amount"]
                self.total_trades += 1
                self.total_profit += profit_pct * pos["amount"] / 100
                if profit_pct > 0:
                    self.winning_trades += 1
                log_print(f"?? STOP-LOSS {pos['symbol']} {pos['side']}: {profit_pct:+.2f}%")
                closed.append(pos)
            
            # Проверка тейк-профита
            elif profit_pct >= TAKE_PROFIT_PCT:
                quantity = round((pos["amount"] * pos["leverage"]) / pos["entry_price"], 6)
                close_futures_position(pos["symbol"], quantity, "BUY" if pos["side"] == "LONG" else "SELL")
                self.balance += pos["amount"]
                self.total_trades += 1
                self.total_profit += profit_pct * pos["amount"] / 100
                if profit_pct > 0:
                    self.winning_trades += 1
                log_print(f"?? TAKE-PROFIT {pos['symbol']} {pos['side']}: {profit_pct:+.2f}%")
                closed.append(pos)
        
        for pos in closed:
            self.positions.remove(pos)
        
        return closed
    
    def run(self):
        log_print("?? Начинаю анализ рынка...")
        
        while True:
            try:
                self.update_balance()
                signals = get_all_signals()
                
                # Получаем текущие цены
                current_prices = {}
                for coin in COINS:
                    price = get_price(coin)
                    if price > 0:
                        current_prices[coin] = price
                
                # Проверяем открытые позиции
                self.check_positions(current_prices)
                
                # Автопилот
                if self.auto_pilot and signals:
                    for sig in signals[:2]:
                        self.execute_trade(sig)
                
                # Вывод в консоль
                os.system('cls' if os.name == 'nt' else 'clear')
                win_rate = (self.winning_trades / max(self.total_trades, 1)) * 100
                
                print("\n" + "=" * 70)
                print("   ? FUTURES TRADING BOT - MEXC")
                print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
                print("=" * 70)
                print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"\n   ?? БАЛАНС: ${self.balance:.2f}")
                print(f"   ? ПЛЕЧО: {LEVERAGE}x")
                print(f"   ?? ПРИБЫЛЬ: ${self.total_profit:.2f}")
                print(f"   ?? ВИНРЕЙТ: {win_rate:.0f}% | СДЕЛОК: {self.total_trades}")
                print(f"   ?? АВТОПИЛОТ: {'? ВКЛ' if self.auto_pilot else '? ВЫКЛ'}")
                
                print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
                for sig in signals[:5]:
                    emoji = "??" if sig["signal"] == "LONG" else "??"
                    print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | RSI={sig['rsi']} | ${sig['price']:.0f}")
                
                print(f"\n   ?? АКТИВНЫХ ПОЗИЦИЙ: {len(self.positions)}")
                for pos in self.positions:
                    current = current_prices.get(pos["symbol"], pos["entry_price"])
                    if pos["side"] == "LONG":
                        profit = (current - pos["entry_price"]) / pos["entry_price"] * 100 * pos["leverage"]
                    else:
                        profit = (pos["entry_price"] - current) / pos["entry_price"] * 100 * pos["leverage"]
                    emoji = "??" if profit > 0 else "??"
                    print(f"      {emoji} {pos['symbol']} {pos['side']} x{pos['leverage']}: {profit:+.1f}%")
                
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
    bot = FuturesBot()
    bot.run()