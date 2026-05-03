# -*- coding: utf-8 -*-
# spot_aggressive.py - АГРЕССИВНАЯ СПОТ СТРАТЕГИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import requests
import hmac
import hashlib
import os
from datetime import datetime
from collections import deque

# ============================================================================
# КЛЮЧИ
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

# ============================================================================
# АГРЕССИВНЫЕ НАСТРОЙКИ
# ============================================================================

# Торгуемые монеты (увеличил количество для большего оборота)
COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", 
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "ETCUSDT"
]

# АГРЕССИВНЫЕ ПАРАМЕТРЫ
TRADE_SIZE = 10           # $10 на сделку (вместо $5) - УВЕЛИЧЕНО!
MAX_POSITIONS = 6         # Максимум 6 открытых позиций (вместо 3) - УВЕЛИЧЕНО!
MIN_CONFIDENCE = 55       # Минимальная уверенность (было 60) - ПОНИЖЕНО!
RSI_BUY_THRESHOLD = 40    # Покупаем при RSI < 40 (было 35) - РАНЬШЕ!
RSI_SELL_THRESHOLD = 60   # Продаём при RSI > 60 (было 65) - РАНЬШЕ!

# Риск-менеджмент (агрессивный)
STOP_LOSS_PCT = 3.5       # Стоп-лосс -3.5% (было -2%)
TAKE_PROFIT_PCT = 6       # Тейк-профит +6% (было +4%)

# Таймауты
POSITION_TIMEOUT = 3600   # Позиция живёт 1 час (было 2)
COOLDOWN_PERIOD = 30       # 30 секунд между сделками по одной монете

# ============================================================================
# ФУНКЦИИ API
# ============================================================================

def sign(params_str):
    return hmac.new(MEXC_API_SECRET.encode(), params_str.encode(), hashlib.sha256).hexdigest()

def get_spot_balance():
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
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=5)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except:
        pass
    return []

def spot_market_buy(symbol, usdt_amount):
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

def spot_market_sell(symbol, usdt_amount):
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

# ============================================================================
# РАСШИРЕННЫЙ АНАЛИЗ (прогретый AI)
# ============================================================================

class AdvancedAnalyzer:
    def __init__(self):
        self.price_history = {}
        self.last_signals = {}
        self.consecutive_wins = 0
        self.consecutive_losses = 0
    
    def calculate_rsi(self, prices, period=14):
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
    
    def calculate_macd(self, prices):
        if len(prices) < 26:
            return 0
        ema12 = sum(prices[-12:]) / 12
        ema26 = sum(prices[-26:]) / 26
        return ema12 - ema26
    
    def calculate_bollinger(self, prices, period=20):
        if len(prices) < period:
            return 0
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        current = prices[-1]
        lower = sma - 2 * std
        upper = sma + 2 * std
        if current <= lower:
            return -1  # Сигнал на покупку
        elif current >= upper:
            return 1   # Сигнал на продажу
        return 0
    
    def calculate_volume_trend(self, volumes):
        if len(volumes) < 10:
            return 0
        avg_vol = sum(volumes[-10:]) / 10
        current_vol = volumes[-1]
        return current_vol / avg_vol if avg_vol > 0 else 1
    
    def analyze(self, symbol, price):
        prices = get_klines(symbol, 50)
        if len(prices) < 30:
            return "HOLD", 0, 50
        
        self.price_history[symbol] = prices
        
        # Множественные индикаторы
        rsi = self.calculate_rsi(prices)
        macd = self.calculate_macd(prices)
        bb = self.calculate_bollinger(prices)
        
        # Агрессивный скоринг
        buy_score = 0
        sell_score = 0
        reasons = []
        
        # RSI (основной сигнал)
        if rsi < RSI_BUY_THRESHOLD:
            buy_score += 40
            reasons.append(f"RSI={rsi:.0f} (перепроданность)")
        elif rsi > RSI_SELL_THRESHOLD:
            sell_score += 40
            reasons.append(f"RSI={rsi:.0f} (перекупленность)")
        
        # MACD
        if macd > 0:
            buy_score += 20
            reasons.append("MACD бычий")
        elif macd < 0:
            sell_score += 20
            reasons.append("MACD медвежий")
        
        # Bollinger Bands
        if bb == -1:
            buy_score += 25
            reasons.append("Цена у нижней полосы")
        elif bb == 1:
            sell_score += 25
            reasons.append("Цена у верхней полосы")
        
        # Анализ тренда
        sma5 = sum(prices[-5:]) / 5
        sma20 = sum(prices[-20:]) / 20
        if sma5 > sma20:
            buy_score += 15
            reasons.append("Краткосрочный тренд вверх")
        elif sma5 < sma20:
            sell_score += 15
            reasons.append("Краткосрочный тренд вниз")
        
        # Моментум
        if len(prices) >= 10:
            momentum = (prices[-1] - prices[-10]) / prices[-10] * 100
            if momentum > 0.5:
                buy_score += min(20, momentum * 2)
                reasons.append(f"Моментум +{momentum:.1f}%")
            elif momentum < -0.5:
                sell_score += min(20, abs(momentum) * 2)
                reasons.append(f"Моментум {momentum:.1f}%")
        
        # Динамическая корректировка на основе прошлых успехов
        if self.consecutive_losses > 2:
            buy_score *= 0.7
            sell_score *= 0.7
        elif self.consecutive_wins > 3:
            buy_score *= 1.2
            sell_score *= 1.2
        
        # Решение
        if buy_score > sell_score and buy_score > 20:
            confidence = min(95, 50 + buy_score)
            return "BUY", confidence, reasons
        elif sell_score > buy_score and sell_score > 20:
            confidence = min(95, 50 + sell_score)
            return "SELL", confidence, reasons
        else:
            return "HOLD", 0, ["Стабилен"]

# ============================================================================
# АГРЕССИВНЫЙ ТОРГОВЫЙ БОТ
# ============================================================================

class AggressiveSpotBot:
    def __init__(self):
        self.analyzer = AdvancedAnalyzer()
        self.balance = 0
        self.positions = []
        self.cooldown = {}
        self.auto_pilot = True
        
        # Статистика
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0
        self.max_profit = 0
        self.max_loss = 0
        
        self.update_balance()
        
        print("\n" + "=" * 70)
        print("   🚀 AGGRESSIVE SPOT TRADING BOT v2.0")
        print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
        print("=" * 70)
        print(f"\n   📊 НАСТРОЙКИ:")
        print(f"      💰 Размер сделки: ${TRADE_SIZE}")
        print(f"      📈 Макс позиций: {MAX_POSITIONS}")
        print(f"      🎯 Мин уверенность: {MIN_CONFIDENCE}%")
        print(f"      📉 RSI покупки: <{RSI_BUY_THRESHOLD}")
        print(f"      📈 RSI продажи: >{RSI_SELL_THRESHOLD}")
        print(f"      🛑 Стоп-лосс: -{STOP_LOSS_PCT}%")
        print(f"      🎯 Тейк-профит: +{TAKE_PROFIT_PCT}%")
        print(f"\n   💰 БАЛАНС: ${self.balance:.2f}")
        print("\n" + "=" * 70)
        print("   🚀 БОТ ЗАПУЩЕН! Торгую агрессивно...")
        print("   💡 Для выхода: Ctrl+C\n")
    
    def update_balance(self):
        self.balance = get_spot_balance()
    
    def scan_all_coins(self):
        """Сканирование всех монет с расширенным анализом"""
        signals = []
        for coin in COINS:
            price = get_price(coin)
            if price == 0:
                continue
            
            signal, confidence, reasons = self.analyzer.analyze(coin, price)
            
            if signal != "HOLD" and confidence >= MIN_CONFIDENCE:
                # Проверка холодной паузы
                if coin in self.cooldown and time.time() - self.cooldown[coin] < COOLDOWN_PERIOD:
                    continue
                
                signals.append({
                    "symbol": coin,
                    "signal": signal,
                    "confidence": confidence,
                    "price": price,
                    "reasons": reasons
                })
        
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def check_positions(self):
        """Проверка открытых позиций на стоп-лосс и тейк-профит"""
        closed = []
        now = time.time()
        
        for pos in self.positions[:]:
            current_price = get_price(pos["symbol"])
            if current_price == 0:
                continue
            
            profit_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
            
            # Обновляем PNL позиции
            pos["current_profit"] = profit_pct
            
            # Стоп-лосс
            if profit_pct <= -STOP_LOSS_PCT:
                pos["exit_price"] = current_price
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "stop_loss"
                closed.append(pos)
                self.positions.remove(pos)
            
            # Тейк-профит
            elif profit_pct >= TAKE_PROFIT_PCT:
                pos["exit_price"] = current_price
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "take_profit"
                closed.append(pos)
                self.positions.remove(pos)
            
            # Таймаут позиции
            elif now - pos["entry_time"] > POSITION_TIMEOUT:
                pos["exit_price"] = current_price
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "timeout"
                closed.append(pos)
                self.positions.remove(pos)
        
        # Обрабатываем закрытые позиции
        for pos in closed:
            profit_usdt = pos["amount"] * pos["profit_pct"] / 100
            self.balance += pos["amount"] + profit_usdt
            self.total_trades += 1
            self.total_profit += profit_usdt
            
            if pos["profit_pct"] > 0:
                self.winning_trades += 1
                self.analyzer.consecutive_wins += 1
                self.analyzer.consecutive_losses = 0
                if pos["profit_pct"] > self.max_profit:
                    self.max_profit = pos["profit_pct"]
                emoji = "🎉"
            else:
                self.losing_trades += 1
                self.analyzer.consecutive_losses += 1
                self.analyzer.consecutive_wins = 0
                if pos["profit_pct"] < self.max_loss:
                    self.max_loss = pos["profit_pct"]
                emoji = "📉"
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {emoji} {pos['exit_reason'].upper()} {pos['symbol']}: {pos['profit_pct']:+.2f}% (${profit_usdt:.2f})")
    
    def execute_trade(self, signal):
        """Исполнение агрессивной сделки"""
        if signal["signal"] == "BUY":
            if self.balance >= TRADE_SIZE and len(self.positions) < MAX_POSITIONS:
                success = spot_market_buy(signal["symbol"], TRADE_SIZE)
                if success:
                    self.balance -= TRADE_SIZE
                    self.positions.append({
                        "symbol": signal["symbol"],
                        "entry_price": signal["price"],
                        "amount": TRADE_SIZE,
                        "entry_time": time.time(),
                        "confidence": signal["confidence"],
                        "reasons": signal["reasons"]
                    })
                    self.cooldown[signal["symbol"]] = time.time()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ ПОКУПКА {signal['symbol']}: ${TRADE_SIZE} по {signal['price']:.0f} (уверенность {signal['confidence']}%)")
                    return True
        
        elif signal["signal"] == "SELL":
            # Ищем позицию для продажи
            for pos in self.positions:
                if pos["symbol"] == signal["symbol"]:
                    success = spot_market_sell(signal["symbol"], TRADE_SIZE)
                    if success:
                        profit_pct = (signal["price"] - pos["entry_price"]) / pos["entry_price"] * 100
                        profit_usdt = TRADE_SIZE * profit_pct / 100
                        self.balance += TRADE_SIZE
                        self.positions.remove(pos)
                        self.total_trades += 1
                        self.total_profit += profit_usdt
                        
                        if profit_pct > 0:
                            self.winning_trades += 1
                            self.analyzer.consecutive_wins += 1
                            self.analyzer.consecutive_losses = 0
                            emoji = "🎉"
                        else:
                            self.losing_trades += 1
                            self.analyzer.consecutive_losses += 1
                            self.analyzer.consecutive_wins = 0
                            emoji = "📉"
                        
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {emoji} ПРОДАЖА {signal['symbol']}: {profit_pct:+.2f}% (${profit_usdt:.2f})")
                        return True
        return False
    
    def run(self):
        while True:
            try:
                self.update_balance()
                signals = self.scan_all_coins()
                self.check_positions()
                
                # Агрессивный автопилот - открываем до 2 новых сделок за цикл
                if self.auto_pilot and signals:
                    trades_opened = 0
                    for signal in signals:
                        if trades_opened >= 2:
                            break
                        if self.execute_trade(signal):
                            trades_opened += 1
                
                # Вывод в консоль
                os.system('cls' if os.name == 'nt' else 'clear')
                win_rate = (self.winning_trades / max(self.total_trades, 1)) * 100
                
                print("\n" + "=" * 70)
                print("   🚀 AGGRESSIVE SPOT BOT - MEXC")
                print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
                print("=" * 70)
                print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"\n   💰 БАЛАНС: ${self.balance:.2f}")
                print(f"   📊 ОБЩАЯ ПРИБЫЛЬ: ${self.total_profit:.2f}")
                print(f"   🏆 ВИНРЕЙТ: {win_rate:.0f}% | СДЕЛОК: {self.total_trades}")
                print(f"   📈 МАКС ПРИБЫЛЬ: +{self.max_profit:.1f}% | МАКС УБЫТОК: {self.max_loss:.1f}%")
                print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ (АГРЕССИВНЫЙ)' if self.auto_pilot else '❌ ВЫКЛ'}")
                
                print(f"\n   🎯 СИГНАЛЫ (топ 8):")
                for sig in signals[:8]:
                    emoji = "📈" if sig["signal"] == "BUY" else "📉"
                    print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | ${sig['price']:.0f} | {sig['reasons'][0][:20]}...")
                
                print(f"\n   📊 ОТКРЫТЫХ ПОЗИЦИЙ: {len(self.positions)}/{MAX_POSITIONS}")
                for pos in self.positions:
                    current = get_price(pos["symbol"])
                    if current > 0:
                        profit = (current - pos["entry_price"]) / pos["entry_price"] * 100
                        bar = "🟢" if profit > 0 else "🔴"
                        print(f"      {bar} {pos['symbol']}: {profit:+.1f}% | ${pos['amount']:.0f} | {pos['confidence']}%")
                
                print("\n" + "=" * 70)
                print("   🎮 [A] Автопилот  [S] Статус  [Q] Выход")
                print("   💡 Агрессивный режим: больше сделок, выше риск")
                print("=" * 70)
                
                time.sleep(8)  # Чаще сканируем для агрессивной торговли
                
            except KeyboardInterrupt:
                print("\n\n🛑 Бот остановлен")
                print(f"📊 ИТОГ: {self.total_trades} сделок, прибыль ${self.total_profit:.2f}, винрейт {(self.winning_trades/max(self.total_trades,1))*100:.0f}%")
                break
            except Exception as e:
                print(f"⚠️ Ошибка: {e}")
                time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = AggressiveSpotBot()
    bot.run()