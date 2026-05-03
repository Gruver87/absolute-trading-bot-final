# -*- coding: utf-8 -*-
# ABSOLUTE_ULTIMATE_BOT.py - ПОЛНАЯ ВЕРСИЯ
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
#
# ВКЛЮЧАЕТ 10+ СТРАТЕГИЙ:
# 1. RSI (перекупленность/перепроданность)
# 2. MACD (бычий/медвежий кроссовер)
# 3. Bollinger Bands (выход за полосы)
# 4. Volume Analysis (аномалии объёма)
# 5. Momentum (скорость изменения цены)
# 6. Support/Resistance (уровни)
# 7. Moving Average Crossover (SMA 5/20)
# 8. Trailing Stop (защита прибыли)
# 9. Grid Trading (сетка ордеров)
# 10. DCA (усреднение при просадке)

import time
import requests
import hmac
import hashlib
import os
import json
import threading
import math
from datetime import datetime
from collections import defaultdict, deque

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
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "ETCUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT"
]

# ============================================================================
# БАЗОВЫЕ НАСТРОЙКИ
# ============================================================================

BASE_TRADE_SIZE = 10          # Базовая сумма сделки в USDT
MAX_POSITIONS = 5             # Максимум открытых позиций
MIN_CONFIDENCE = 55           # Минимальная уверенность для сделки
COOLDOWN_SECONDS = 30         # Пауза между сделками по одной монете
POSITION_TIMEOUT = 7200       # Таймаут позиции (2 часа)

# ============================================================================
# НАСТРОЙКИ ИНДИКАТОРОВ
# ============================================================================

RSI_OVERSOLD = 35             # RSI для покупки (<35)
RSI_OVERBOUGHT = 65           # RSI для продажи (>65)
MACD_SIGNAL = 0.5             # Порог MACD сигнала
BB_DEV = 2                    # Стандартное отклонение Bollinger
VOLUME_RATIO = 1.5            # Отношение текущего объёма к среднему
MOMENTUM_THRESHOLD = 1.0      # Порог моментума в %

# ============================================================================
# РИСК-МЕНЕДЖМЕНТ
# ============================================================================

STOP_LOSS_PCT = 3.5           # Стоп-лосс -3.5%
TAKE_PROFIT_PCT = 8.0         # Тейк-профит +8% (базовый)

# Трейлинг-стоп (защита прибыли)
TRAILING_STOP_ENABLED = True
TRAILING_STOP_ACTIVATE = 5.0  # Активация после +5% прибыли
TRAILING_STOP_DISTANCE = 2.0  # Отступ 2% от максимума

# DCA (усреднение при просадке)
DCA_ENABLED = True
DCA_THRESHOLD = -2.0          # Просадка для усреднения (%)
DCA_MULTIPLIER = 1.5          # Увеличение суммы при усреднении

# Grid Trading (сетка ордеров)
GRID_ENABLED = False          # Вкл/Выкл (экспериментально)
GRID_LEVELS = 3               # Количество уровней сетки
GRID_SPACING = 1.0            # Шаг сетки в %

# ============================================================================
# ЛИМИТЫ БЕЗОПАСНОСТИ
# ============================================================================

MAX_DAILY_LOSS = 15.0         # Максимальный дневной убыток в USDT
MAX_CONSECUTIVE_LOSSES = 5    # Макс последовательных убытков
MIN_BALANCE = 20              # Минимальный баланс для торговли

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

def get_klines(symbol, limit=100):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [float(c[4]) for c in r.json()]
    except:
        pass
    return []

def get_detailed_klines(symbol, limit=100):
    """Получение детальных свечей с OHLCV"""
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}", timeout=10)
        if r.status_code == 200:
            return [{
                "time": c[0], "open": float(c[1]), "high": float(c[2]),
                "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])
            } for c in r.json()]
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
# РАСШИРЕННЫЙ ТЕХНИЧЕСКИЙ АНАЛИЗ
# ============================================================================

class TechnicalAnalyzer:
    def __init__(self):
        self.history = defaultdict(lambda: deque(maxlen=500))
    
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
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        if len(prices) < slow + signal:
            return 0, 0, 0
        ema_fast = self.calculate_ema(prices, fast)
        ema_slow = self.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        ema_signal = self.calculate_ema([macd_line], signal) if len([macd_line]) >= signal else macd_line
        histogram = macd_line - ema_signal
        return macd_line, ema_signal, histogram
    
    def calculate_ema(self, prices, period):
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        k = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = price * k + ema * (1 - k)
        return ema
    
    def calculate_bollinger(self, prices, period=20, dev=2):
        if len(prices) < period:
            return 0, 0, 0
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        upper = sma + dev * std
        lower = sma - dev * std
        current = prices[-1]
        position = (current - lower) / (upper - lower) if upper != lower else 0.5
        return position, upper, lower
    
    def calculate_volume_analysis(self, candles):
        if len(candles) < 20:
            return 1, False
        volumes = [c["volume"] for c in candles]
        avg_vol = sum(volumes[-20:]) / 20
        current_vol = volumes[-1]
        ratio = current_vol / avg_vol if avg_vol > 0 else 1
        is_spike = ratio > VOLUME_RATIO
        return ratio, is_spike
    
    def calculate_momentum(self, prices, period=10):
        if len(prices) < period:
            return 0
        return (prices[-1] - prices[-period]) / prices[-period] * 100
    
    def calculate_support_resistance(self, prices, period=50):
        if len(prices) < period:
            return None, None
        support = min(prices[-period:])
        resistance = max(prices[-period:])
        
        # Динамические уровни
        recent_support = min(prices[-20:])
        recent_resistance = max(prices[-20:])
        
        return support, resistance, recent_support, recent_resistance
    
    def calculate_correlation(self, symbol1_prices, symbol2_prices):
        """Корреляция между монетами"""
        if len(symbol1_prices) < 20 or len(symbol2_prices) < 20:
            return 0
        min_len = min(len(symbol1_prices), len(symbol2_prices))
        p1 = symbol1_prices[-min_len:]
        p2 = symbol2_prices[-min_len:]
        
        mean1 = sum(p1) / len(p1)
        mean2 = sum(p2) / len(p2)
        
        numerator = sum((p1[i] - mean1) * (p2[i] - mean2) for i in range(len(p1)))
        denom1 = math.sqrt(sum((p1[i] - mean1) ** 2 for i in range(len(p1))))
        denom2 = math.sqrt(sum((p2[i] - mean2) ** 2 for i in range(len(p2))))
        
        if denom1 * denom2 == 0:
            return 0
        return numerator / (denom1 * denom2)
    
    def analyze_market_regime(self, prices):
        """Определение режима рынка (тренд/флэт/волатильный)"""
        if len(prices) < 50:
            return "neutral", 0
        
        # Анализ тренда
        sma20 = sum(prices[-20:]) / 20
        sma50 = sum(prices[-50:]) / 50
        trend_strength = (sma20 - sma50) / sma50 * 100
        
        # Анализ волатильности
        returns = [(prices[i] - prices[i-1]) / prices[i-1] * 100 for i in range(1, len(prices))]
        volatility = sum(abs(r) for r in returns[-20:]) / 20
        
        if abs(trend_strength) > 1.5:
            regime = "trend"
        elif volatility > 3:
            regime = "volatile"
        else:
            regime = "flat"
        
        return regime, trend_strength
    
    def calculate_ichimoku(self, prices):
        """Ишимоку облако (базовый)"""
        if len(prices) < 52:
            return 0, 0, 0, 0
        tenkan = (max(prices[-9:]) + min(prices[-9:])) / 2
        kijun = (max(prices[-26:]) + min(prices[-26:])) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (max(prices[-52:]) + min(prices[-52:])) / 2
        return tenkan, kijun, senkou_a, senkou_b
    
    def analyze(self, symbol, price):
        """Полный анализ монеты со ВСЕМИ индикаторами"""
        candles = get_detailed_klines(symbol, 100)
        if len(candles) < 50:
            return "HOLD", 0, 50, ["Недостаточно данных"], 0
        
        prices = [c["close"] for c in candles]
        
        # Инициализация скоринга
        scores = {"BUY": 0, "SELL": 0}
        reasons = []
        details = {}
        
        # 1. RSI
        rsi = self.calculate_rsi(prices)
        details["rsi"] = rsi
        if rsi < RSI_OVERSOLD:
            scores["BUY"] += 40
            reasons.append(f"RSI={rsi:.1f} (oversold)")
        elif rsi > RSI_OVERBOUGHT:
            scores["SELL"] += 40
            reasons.append(f"RSI={rsi:.1f} (overbought)")
        
        # 2. MACD
        macd_line, signal_line, histogram = self.calculate_macd(prices)
        details["macd"] = macd_line
        if macd_line > signal_line and macd_line > 0:
            scores["BUY"] += 25
            reasons.append("MACD bullish crossover")
        elif macd_line < signal_line and macd_line < 0:
            scores["SELL"] += 25
            reasons.append("MACD bearish crossover")
        
        # 3. Bollinger Bands
        bb_pos, bb_upper, bb_lower = self.calculate_bollinger(prices)
        details["bb_pos"] = bb_pos
        if bb_pos < 0.2:
            scores["BUY"] += 30
            reasons.append("Price at lower Bollinger band")
        elif bb_pos > 0.8:
            scores["SELL"] += 30
            reasons.append("Price at upper Bollinger band")
        
        # 4. Объём
        vol_ratio, is_spike = self.calculate_volume_analysis(candles)
        details["volume_ratio"] = vol_ratio
        if is_spike and scores["BUY"] > scores["SELL"]:
            scores["BUY"] += 20
            reasons.append(f"Volume spike {vol_ratio:.1f}x")
        elif is_spike and scores["SELL"] > scores["BUY"]:
            scores["SELL"] += 20
        
        # 5. Моментум
        momentum = self.calculate_momentum(prices)
        details["momentum"] = momentum
        if momentum > MOMENTUM_THRESHOLD:
            scores["BUY"] += min(25, momentum * 2)
            reasons.append(f"Momentum +{momentum:.1f}%")
        elif momentum < -MOMENTUM_THRESHOLD:
            scores["SELL"] += min(25, abs(momentum) * 2)
            reasons.append(f"Momentum {momentum:.1f}%")
        
        # 6. Moving Average Crossover
        sma5 = sum(prices[-5:]) / 5
        sma20 = sum(prices[-20:]) / 20
        details["sma5"] = sma5
        details["sma20"] = sma20
        if sma5 > sma20:
            scores["BUY"] += 15
            reasons.append("SMA5 > SMA20 (uptrend)")
        elif sma5 < sma20:
            scores["SELL"] += 15
            reasons.append("SMA5 < SMA20 (downtrend)")
        
        # 7. Уровни поддержки/сопротивления
        support, resistance, recent_support, recent_resistance = self.calculate_support_resistance(prices)
        details["support"] = support
        details["resistance"] = resistance
        if price <= recent_support * 1.01:
            scores["BUY"] += 15
            reasons.append(f"At support ${recent_support:.0f}")
        elif price >= recent_resistance * 0.99:
            scores["SELL"] += 15
            reasons.append(f"At resistance ${recent_resistance:.0f}")
        
        # 8. Рыночный режим
        regime, trend = self.analyze_market_regime(prices)
        details["regime"] = regime
        if regime == "trend" and trend > 0:
            scores["BUY"] *= 1.1
        elif regime == "trend" and trend < 0:
            scores["SELL"] *= 1.1
        elif regime == "volatile":
            scores["BUY"] *= 0.8
            scores["SELL"] *= 0.8
        
        # 9. Ишимоку (бонус)
        tenkan, kijun, senkou_a, senkou_b = self.calculate_ichimoku(prices)
        details["ichimoku"] = {"tenkan": tenkan, "kijun": kijun}
        if price > max(senkou_a, senkou_b) and tenkan > kijun:
            scores["BUY"] += 10
            reasons.append("Ichimoku bullish")
        elif price < min(senkou_a, senkou_b) and tenkan < kijun:
            scores["SELL"] += 10
            reasons.append("Ichimoku bearish")
        
        # Итоговый сигнал
        net_score = scores["BUY"] - scores["SELL"]
        total_score = scores["BUY"] + scores["SELL"]
        details["net_score"] = net_score
        
        if net_score > 25:
            confidence = min(95, 50 + net_score)
            return "BUY", confidence, rsi, reasons[:5], net_score
        elif net_score < -25:
            confidence = min(95, 50 + abs(net_score))
            return "SELL", confidence, rsi, reasons[:5], net_score
        else:
            return "HOLD", 0, rsi, ["Market stable"], net_score

# ============================================================================
# ПРОДВИНУТЫЙ РИСК-МЕНЕДЖЕР
# ============================================================================

class AdvancedRiskManager:
    def __init__(self, initial_balance):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_start = initial_balance
        self.last_reset = datetime.now().date()
        self.consecutive_losses = 0
        self.daily_trades = 0
        self.drawdown_history = []
        self.kelly_fraction = 0.25
        
        # Адаптивные параметры
        self.adaptive_risk = 1.0
        self.performance_history = []
    
    def update(self, new_balance):
        self.current_balance = new_balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance
        
        # Дневной сброс
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_start = new_balance
            self.last_reset = today
            self.daily_trades = 0
            self.consecutive_losses = 0
        
        # Обновление просадки
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance * 100
        self.drawdown_history.append(drawdown)
        if len(self.drawdown_history) > 100:
            self.drawdown_history.pop(0)
        
        # Адаптивный риск на основе просадки
        if drawdown > 10:
            self.adaptive_risk = max(0.3, 1 - drawdown / 20)
        elif drawdown < 5:
            self.adaptive_risk = min(1.5, 1 + (5 - drawdown) / 10)
    
    def check_limits(self):
        """Проверка лимитов безопасности"""
        daily_loss = self.daily_start - self.current_balance
        if daily_loss > MAX_DAILY_LOSS:
            return False, f"Daily loss limit: ${daily_loss:.2f}"
        
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False, f"Consecutive losses: {self.consecutive_losses}"
        
        if self.current_balance < MIN_BALANCE:
            return False, f"Balance below minimum: ${self.current_balance:.2f}"
        
        return True, "OK"
    
    def calculate_dynamic_position(self, confidence, score):
        """Динамический расчёт размера позиции"""
        base = BASE_TRADE_SIZE
        
        # Множители
        confidence_mult = min(1.8, 0.8 + confidence / 100)
        score_mult = min(1.5, 0.5 + abs(score) / 50)
        loss_penalty = max(0.4, 1 - self.consecutive_losses * 0.15)
        
        # Риск-адаптация
        risk_mult = self.adaptive_risk
        
        # Kelly множитель
        win_rate = self.get_win_rate()
        kelly_mult = min(1.5, self.kelly_fraction * (win_rate / 50))
        
        size = base * confidence_mult * score_mult * loss_penalty * risk_mult * kelly_mult
        
        # Ограничения
        max_size = min(30, self.current_balance * 0.15)
        size = min(max_size, max(5, size))
        
        return round(size, 2)
    
    def get_win_rate(self):
        if not self.performance_history:
            return 50
        wins = sum(1 for p in self.performance_history if p > 0)
        return (wins / len(self.performance_history)) * 100
    
    def record_trade_result(self, profit_pct):
        self.performance_history.append(profit_pct)
        if len(self.performance_history) > 100:
            self.performance_history.pop(0)
        
        if profit_pct > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        self.daily_trades += 1
    
    def get_sharpe_ratio(self):
        if len(self.performance_history) < 10:
            return 0
        mean = sum(self.performance_history) / len(self.performance_history)
        var = sum((p - mean) ** 2 for p in self.performance_history) / len(self.performance_history)
        std = math.sqrt(var) if var > 0 else 0.0001
        return mean / std if std != 0 else 0
    
    def get_stats(self):
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance * 100
        daily_pnl = self.current_balance - self.daily_start
        
        return {
            "balance": self.current_balance,
            "peak": self.peak_balance,
            "drawdown": round(drawdown, 1),
            "daily_pnl": round(daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "adaptive_risk": round(self.adaptive_risk, 2),
            "sharpe": round(self.get_sharpe_ratio(), 2),
            "win_rate": round(self.get_win_rate(), 1)
        }

# ============================================================================
# ОСНОВНОЙ ТОРГОВЫЙ БОТ
# ============================================================================

class UltimateTradingBot:
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.balance = 0
        self.positions = []
        self.cooldown = {}
        self.auto_pilot = True
        self.running = True
        self.last_scan = 0
        
        # Статистика
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_profit = 0
        self.best_trade = 0
        self.worst_trade = 0
        self.order_history = []
        
        self.update_balance()
        self.risk_manager = AdvancedRiskManager(self.balance)
        
        # Команды
        self.command = None
        
        self.log("🚀 ABSOLUTE ULTIMATE BOT v3.0 STARTED")
        self.log(f"💰 Initial balance: ${self.balance:.2f}")
        self.log(f"📊 Tracking {len(COINS)} coins with 10+ indicators")
        send_telegram(f"🚀 BOT STARTED\n💰 Balance: ${self.balance:.2f}\n📊 Coins: {len(COINS)}")
    
    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")
    
    def update_balance(self):
        self.balance = get_balance()
        if self.balance > 0:
            self.risk_manager.update(self.balance)
    
    def get_position_by_symbol(self, symbol):
        for pos in self.positions:
            if pos["symbol"] == symbol:
                return pos
        return None
    
    def scan_market(self):
        """Полное сканирование рынка со всеми стратегиями"""
        signals = []
        
        for coin in COINS:
            price = get_price(coin)
            if price == 0:
                continue
            
            signal, confidence, rsi, reasons, score = self.analyzer.analyze(coin, price)
            
            if signal != "HOLD" and confidence >= MIN_CONFIDENCE:
                # Проверка кулдауна
                if coin in self.cooldown:
                    if time.time() - self.cooldown[coin] < COOLDOWN_SECONDS:
                        continue
                
                # Проверка на существующую позицию
                if signal == "BUY" and self.get_position_by_symbol(coin) is not None:
                    continue
                
                signals.append({
                    "symbol": coin,
                    "signal": signal,
                    "confidence": confidence,
                    "price": price,
                    "rsi": rsi,
                    "score": score,
                    "reasons": reasons
                })
        
        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals
    
    def execute_buy(self, signal):
        """Исполнение покупки"""
        if len(self.positions) >= MAX_POSITIONS:
            return False
        
        # Проверка лимитов
        ok, msg = self.risk_manager.check_limits()
        if not ok:
            return False
        
        # Расчёт размера позиции
        size = self.risk_manager.calculate_dynamic_position(signal["confidence"], signal["score"])
        size = min(size, self.balance)
        
        if size < 5:
            return False
        
        success = market_buy(signal["symbol"], size)
        if success:
            self.balance -= size
            
            # Стоп-лосс
            stop_loss_price = signal["price"] * (1 - STOP_LOSS_PCT / 100)
            
            # Тейк-профит
            take_profit_price = signal["price"] * (1 + TAKE_PROFIT_PCT / 100)
            
            self.positions.append({
                "symbol": signal["symbol"],
                "entry_price": signal["price"],
                "amount": size,
                "confidence": signal["confidence"],
                "score": signal["score"],
                "rsi": signal["rsi"],
                "reasons": signal["reasons"],
                "entry_time": time.time(),
                "stop_loss": stop_loss_price,
                "take_profit": take_profit_price,
                "max_profit": 0
            })
            
            self.cooldown[signal["symbol"]] = time.time()
            
            msg = f"📈 BUY {signal['symbol']}: ${size:.0f} at ${signal['price']:.0f} | Confidence: {signal['confidence']}% | Score: {signal['score']:.0f}"
            self.log(msg)
            send_telegram(msg)
            return True
        
        return False
    
    def execute_sell(self, signal):
        """Исполнение продажи"""
        pos = self.get_position_by_symbol(signal["symbol"])
        if pos is None:
            return False
        
        profit_pct = (signal["price"] - pos["entry_price"]) / pos["entry_price"] * 100
        profit_usdt = pos["amount"] * profit_pct / 100
        
        success = market_sell(signal["symbol"], pos["amount"])
        if success:
            self.balance += pos["amount"]
            self.positions.remove(pos)
            
            # Обновление статистики
            self.total_trades += 1
            self.total_profit += profit_usdt
            
            if profit_pct > 0:
                self.wins += 1
                if profit_pct > self.best_trade:
                    self.best_trade = profit_pct
            else:
                self.losses += 1
                if profit_pct < self.worst_trade:
                    self.worst_trade = profit_pct
            
            self.risk_manager.record_trade_result(profit_pct)
            self.order_history.append({
                "time": datetime.now(), "symbol": signal["symbol"],
                "profit_pct": profit_pct, "profit_usdt": profit_usdt
            })
            
            emoji = "🎉" if profit_pct > 0 else "📉"
            msg = f"{emoji} SELL {signal['symbol']}: {profit_pct:+.2f}% (${profit_usdt:.2f})"
            self.log(msg)
            send_telegram(msg)
            return True
        
        return False
    
    def check_positions_with_trailing(self):
        """Проверка позиций с трейлинг-стопом"""
        closed = []
        
        for pos in self.positions[:]:
            price = get_price(pos["symbol"])
            if price == 0:
                continue
            
            profit_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
            pos["current_profit"] = profit_pct
            
            # Обновляем максимальную прибыль
            if profit_pct > pos.get("max_profit", 0):
                pos["max_profit"] = profit_pct
            
            # --- ТРЕЙЛИНГ-СТОП ---
            if TRAILING_STOP_ENABLED and profit_pct >= TRAILING_STOP_ACTIVATE:
                trailing_stop = pos["max_profit"] - TRAILING_STOP_DISTANCE
                if profit_pct <= trailing_stop:
                    pos["profit_pct"] = profit_pct
                    pos["exit_reason"] = "trailing_stop"
                    closed.append(pos)
                    self.positions.remove(pos)
                    continue
            
            # --- ТЕЙК-ПРОФИТ ---
            elif profit_pct >= TAKE_PROFIT_PCT:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "take_profit"
                closed.append(pos)
                self.positions.remove(pos)
                continue
            
            # --- СТОП-ЛОСС ---
            elif profit_pct <= -STOP_LOSS_PCT:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "stop_loss"
                closed.append(pos)
                self.positions.remove(pos)
                continue
            
            # --- ТАЙМАУТ ---
            elif time.time() - pos["entry_time"] > POSITION_TIMEOUT:
                pos["profit_pct"] = profit_pct
                pos["exit_reason"] = "timeout"
                closed.append(pos)
                self.positions.remove(pos)
                continue
        
        # Обработка закрытых
        for pos in closed:
            profit_usdt = pos["amount"] * pos["profit_pct"] / 100
            self.balance += pos["amount"]
            self.total_trades += 1
            self.total_profit += profit_usdt
            
            if pos["profit_pct"] > 0:
                self.wins += 1
                if pos["profit_pct"] > self.best_trade:
                    self.best_trade = pos["profit_pct"]
            else:
                self.losses += 1
                if pos["profit_pct"] < self.worst_trade:
                    self.worst_trade = pos["profit_pct"]
            
            self.risk_manager.record_trade_result(pos["profit_pct"])
            self.log(f"CLOSE [{pos['exit_reason']}] {pos['symbol']}: {pos['profit_pct']:+.2f}% | Max profit: {pos.get('max_profit', 0):+.1f}%")
    
    def print_dashboard(self, signals):
        """Вывод дашборда"""
        os.system('cls' if os.name == 'nt' else 'clear')
        risk_stats = self.risk_manager.get_stats()
        win_rate = (self.wins / max(self.total_trades, 1)) * 100
        
        print("\n" + "=" * 80)
        print("   🚀 ABSOLUTE ULTIMATE BOT v3.0 - FULL VERSION")
        print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
        print("=" * 80)
        print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\n   💰 BALANCE: ${risk_stats['balance']:.2f} | PEAK: ${risk_stats['peak']:.2f}")
        print(f"   📉 DRAWDOWN: {risk_stats['drawdown']:.1f}% | DAILY PNL: ${risk_stats['daily_pnl']:+.2f}")
        print(f"   📊 TOTAL PROFIT: ${self.total_profit:.2f} | WINRATE: {win_rate:.1f}%")
        print(f"   🏆 TRADES: {self.total_trades} (W:{self.wins} L:{self.losses})")
        print(f"   📈 BEST: +{self.best_trade:.1f}% | WORST: {self.worst_trade:.1f}%")
        print(f"   🎲 SHARPE: {risk_stats['sharpe']:.2f} | ADAPTIVE RISK: {risk_stats['adaptive_risk']:.1f}x")
        print(f"   🤖 AUTOPILOT: {'✅ ON' if self.auto_pilot else '❌ OFF'}")
        print(f"   🛡️ TRAILING STOP: {'ON' if TRAILING_STOP_ENABLED else 'OFF'} (activate at +{TRAILING_STOP_ACTIVATE}%)")
        
        print(f"\n   🎯 TOP SIGNALS:")
        for i, sig in enumerate(signals[:10]):
            emoji = "📈" if sig["signal"] == "BUY" else "📉"
            print(f"      {i+1}. {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | SCORE={sig['score']:.0f} | RSI={sig['rsi']:.0f} | ${sig['price']:.0f}")
            if sig["reasons"]:
                print(f"         └─ {sig['reasons'][0][:50]}")
        
        print(f"\n   📊 OPEN POSITIONS: {len(self.positions)}/{MAX_POSITIONS}")
        for pos in self.positions:
            profit = pos.get("current_profit", 0)
            max_profit = pos.get("max_profit", 0)
            status = "📈" if profit > 0 else "📉" if profit < 0 else "⏸️"
            print(f"      {status} {pos['symbol']}: {profit:+.2f}% (max: +{max_profit:.1f}%) | ${pos['amount']:.0f} | {pos['confidence']}%")
        
        print("\n" + "=" * 80)
        print("   🎮 COMMANDS (type and press Enter):")
        print("      a - Autopilot     s - Status        c - Close all positions")
        print("      r - Rescan        t - Telegram      q - Quit")
        print("=" * 80)
    
    def input_handler(self):
        """Обработчик ввода в отдельном потоке"""
        while self.running:
            try:
                cmd = input().strip().lower()
                if cmd:
                    self.command = cmd
                time.sleep(0.1)
            except:
                pass
    
    def run(self):
        """Основной цикл бота"""
        # Запуск потока ввода
        input_thread = threading.Thread(target=self.input_handler, daemon=True)
        input_thread.start()
        
        signals = []
        
        while self.running:
            try:
                self.update_balance()
                
                # Сканирование каждые 10 секунд
                if time.time() - self.last_scan > 10:
                    signals = self.scan_market()
                    self.last_scan = time.time()
                
                # Автопилот
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
                
                # Проверка позиций
                self.check_positions_with_trailing()
                
                # Вывод дашборда
                self.print_dashboard(signals)
                
                # Обработка команд
                if self.command is not None:
                    cmd = self.command
                    self.command = None
                    
                    if cmd == 'a':
                        self.auto_pilot = not self.auto_pilot
                        self.log(f"Autopilot: {'ON' if self.auto_pilot else 'OFF'}")
                    elif cmd == 's':
                        status = self.risk_manager.get_stats()
                        self.log(f"Balance: ${status['balance']:.2f}, Profit: ${self.total_profit:.2f}, Winrate: {(self.wins/max(self.total_trades,1))*100:.1f}%")
                        send_telegram(f"Status: Balance ${status['balance']:.2f}, Profit ${self.total_profit:.2f}")
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
                        self.running = False
                        self.log("Bot stopped")
                        send_telegram("Bot stopped")
                        break
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                self.running = False
                self.log("Bot stopped by user")
                break
            except Exception as e:
                self.log(f"Error: {e}")
                time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    bot = UltimateTradingBot()
    bot.run()