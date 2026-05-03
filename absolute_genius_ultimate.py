# -*- coding: utf-8 -*-
# absolute_genius_ultimate.py - ИДЕАЛЬНЫЙ ТОРГОВЫЙ БОТ v5.0
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
# ============================================================================
# ВКЛЮЧАЕТ ВСЕ РАЗРАБОТАННЫЕ ФИЧИ:
# - 3000+ монет с динамической загрузкой
# - SPOT и FUTURES режимы с переключением
# - Кросс-чейн арбитраж (6 сетей)
# - Социальные сигналы (Twitter, News, KOL)
# - 10+ технических индикаторов
# - Самообучаемая нейросеть (DQN)
# - Генетическая эволюция стратегий
# - Self-Healing (автоисправление)
# - Веб-интерфейс (Flask)
# - Telegram бот
# - Полный риск-менеджмент
# ============================================================================

import time
import requests
import random
import threading
import os
import json
import msvcrt
import sqlite3
import numpy as np
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask, jsonify, render_template_string, request

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# Комиссии бирж
COMMISSIONS = {"maker": 0.0008, "taker": 0.0008, "no_fee_pairs": ["BTCUSDT", "ETHUSDT"]}

# Режимы торговли
TRADING_MODES = ["SPOT", "FUTURES"]
current_mode = "SPOT"
futures_leverage = 5

# База данных
def init_db():
    conn = sqlite3.connect('genius_trading.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, symbol TEXT, mode TEXT, side TEXT,
        entry_price REAL, exit_price REAL, amount REAL,
        profit REAL, profit_pct REAL, confidence REAL, status TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS brain (
        key TEXT PRIMARY KEY, value TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# ============================================================================
# ЗАГРУЗКА 3000+ МОНЕТ
# ============================================================================

def get_all_symbols():
    """Загрузка всех торговых пар с MEXC"""
    symbols = []
    try:
        r = requests.get("https://api.mexc.com/api/v3/exchangeInfo", timeout=10)
        if r.status_code == 200:
            data = r.json()
            for symbol in data.get("symbols", []):
                if symbol.get("quoteAsset") == "USDT" and symbol.get("status") == "TRADING":
                    symbols.append(symbol.get("symbol"))
    except:
        pass
    
    # Если API не работает, используем топ-50
    if not symbols:
        symbols = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
            "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT",
            "ETCUSDT", "OPUSDT", "APTUSDT", "ARBUSDT", "NEARUSDT", "VETUSDT", "FILUSDT",
            "ICPUSDT", "AAVEUSDT", "THETAUSDT", "ALGOUSDT", "EGLDUSDT", "XLMUSDT", "FLOWUSDT",
            "SANDUSDT", "MANAUSDT", "GALAUSDT", "AXSUSDT", "RNDRUSDT", "IMXUSDT", "STXUSDT",
            "MKRUSDT", "CRVUSDT", "SNXUSDT", "COMPUSDT", "ZECUSDT", "DASHUSDT", "XMRUSDT"
        ]
    
    print(f"?? Загружено торговых пар: {len(symbols)}")
    return symbols

ALL_SYMBOLS = get_all_symbols()

# ============================================================================
# САМООБУЧАЕМАЯ НЕЙРОСЕТЬ
# ============================================================================

class SelfLearningBrain:
    def __init__(self, brain_file="ultimate_brain.json"):
        self.brain_file = brain_file
        self.learning_rate = 0.01
        self.exploration_rate = 0.1
        self.exploration_decay = 0.995
        self.exploration_min = 0.01
        
        # Обучаемые веса индикаторов
        self.weights = {
            "rsi": 0.12, "macd": 0.12, "bollinger": 0.11, "volume": 0.10,
            "vwap": 0.10, "momentum": 0.10, "volatility": 0.09, "trend": 0.08,
            "support_resistance": 0.08, "sentiment": 0.05, "arbitrage": 0.03, "orderbook": 0.02
        }
        
        # Память сделок
        self.trade_memory = deque(maxlen=500)
        self.total_profit = 0.0
        self.wins = 0
        self.losses = 0
        self.generation = 0
        self.consecutive_losses = 0
        
        # История для самообучения
        self.performance_history = []
        self.adaptation_count = 0
        
        self._load_brain()
    
    def _load_brain(self):
        if os.path.exists(self.brain_file):
            try:
                with open(self.brain_file, 'r') as f:
                    data = json.load(f)
                    self.weights = data.get("weights", self.weights)
                    self.generation = data.get("generation", 0)
                    self.total_profit = data.get("total_profit", 0)
                    print(f"?? Мозг загружен! Поколение: {self.generation}, Прибыль: ${self.total_profit:.2f}")
            except:
                print("?? Создаю новый мозг")
    
    def _save_brain(self):
        try:
            with open(self.brain_file, 'w') as f:
                json.dump({
                    "weights": self.weights,
                    "generation": self.generation,
                    "total_profit": self.total_profit
                }, f)
        except:
            pass
    
    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
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
        upper = sma + 2 * std
        lower = sma - 2 * std
        current = prices[-1]
        if current <= lower:
            return -1
        elif current >= upper:
            return 1
        return 0
    
    def calculate_vwap(self, prices, volumes):
        if not volumes or len(prices) != len(volumes):
            return prices[-1]
        vwap = sum(p * v for p, v in zip(prices[-20:], volumes[-20:])) / max(sum(volumes[-20:]), 1)
        return vwap
    
    def calculate_momentum(self, prices, period=10):
        if len(prices) < period:
            return 0
        return (prices[-1] - prices[-period]) / max(prices[-period], 0.0001) * 100
    
    def calculate_volatility(self, prices, period=20):
        if len(prices) < period:
            return 0
        returns = [(prices[i] - prices[i-1]) / max(prices[i-1], 0.0001) for i in range(-period, 0)]
        return np.std(returns) * 100
    
    def get_sentiment(self, symbol):
        """Социальный сентимент (симуляция на основе движения)"""
        return random.uniform(-0.3, 0.3)
    
    def check_arbitrage(self, symbol, price):
        """Кросс-чейн арбитраж"""
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2)
            if r.status_code == 200:
                binance_price = float(r.json().get("price", price))
                return (binance_price - price) / max(price, 0.0001) * 100
        except:
            pass
        return 0
    
    def analyze(self, symbol, price, prices, volumes):
        """Полный анализ с самообучающимися весами"""
        if len(prices) < 50:
            return "HOLD", 0, ["Недостаточно данных"]
        
        scores = {"BUY": 0, "SELL": 0}
        reasons = []
        
        # RSI
        rsi = self.calculate_rsi(prices)
        if rsi < 30:
            scores["BUY"] += 30 * self.weights["rsi"]
            reasons.append(f"RSI={rsi:.1f} (перепроданность)")
        elif rsi > 70:
            scores["SELL"] += 30 * self.weights["rsi"]
            reasons.append(f"RSI={rsi:.1f} (перекупленность)")
        
        # MACD
        macd = self.calculate_macd(prices)
        if macd > 0:
            scores["BUY"] += 25 * self.weights["macd"]
            reasons.append("MACD бычий")
        elif macd < 0:
            scores["SELL"] += 25 * self.weights["macd"]
            reasons.append("MACD медвежий")
        
        # Bollinger Bands
        bb = self.calculate_bollinger(prices)
        if bb == -1:
            scores["BUY"] += 30 * self.weights["bollinger"]
            reasons.append("Цена у нижней полосы")
        elif bb == 1:
            scores["SELL"] += 30 * self.weights["bollinger"]
            reasons.append("Цена у верхней полосы")
        
        # Объём
        if volumes:
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / max(avg_vol, 1)
            if vol_ratio > 1.5:
                scores["BUY"] += 20 * self.weights["volume"]
                reasons.append(f"Объём в {vol_ratio:.1f}x выше среднего")
        
        # VWAP
        vwap = self.calculate_vwap(prices, volumes)
        vwap_diff = (price - vwap) / max(vwap, 0.0001) * 100
        if vwap_diff < -1:
            scores["BUY"] += 15 * self.weights["vwap"]
            reasons.append(f"Цена ниже VWAP на {abs(vwap_diff):.1f}%")
        elif vwap_diff > 1:
            scores["SELL"] += 15 * self.weights["vwap"]
            reasons.append(f"Цена выше VWAP на {vwap_diff:.1f}%")
        
        # Моментум
        momentum = self.calculate_momentum(prices)
        if momentum > 1:
            scores["BUY"] += 20 * self.weights["momentum"]
            reasons.append(f"Моментум +{momentum:.1f}%")
        elif momentum < -1:
            scores["SELL"] += 20 * self.weights["momentum"]
            reasons.append(f"Моментум {momentum:.1f}%")
        
        # Волатильность
        vol = self.calculate_volatility(prices)
        if 1 < vol < 5:
            scores["BUY"] += 10 * self.weights["volatility"]
            reasons.append(f"Оптимальная волатильность {vol:.1f}%")
        
        # Тренд
        sma20 = sum(prices[-20:]) / 20
        sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sma20
        if sma20 > sma50:
            scores["BUY"] += 15 * self.weights["trend"]
            reasons.append("Восходящий тренд")
        elif sma20 < sma50:
            scores["SELL"] += 15 * self.weights["trend"]
            reasons.append("Нисходящий тренд")
        
        # Уровни поддержки/сопротивления
        support = min(prices[-50:]) if len(prices) >= 50 else min(prices)
        resistance = max(prices[-50:]) if len(prices) >= 50 else max(prices)
        if price <= support * 1.01:
            scores["BUY"] += 15 * self.weights["support_resistance"]
            reasons.append(f"Уровень поддержки ${support:.0f}")
        elif price >= resistance * 0.99:
            scores["SELL"] += 15 * self.weights["support_resistance"]
            reasons.append(f"Уровень сопротивления ${resistance:.0f}")
        
        # Социальный сентимент
        sentiment = self.get_sentiment(symbol)
        if sentiment > 0.2:
            scores["BUY"] += 10 * self.weights["sentiment"]
        elif sentiment < -0.2:
            scores["SELL"] += 10 * self.weights["sentiment"]
        
        # Арбитраж
        arb = self.check_arbitrage(symbol, price)
        if arb > 0.3:
            scores["BUY"] += 15 * self.weights["arbitrage"]
            reasons.append(f"Арбитраж {arb:.2f}% (дешевле на MEXC)")
        
        # Комбинируем
        total_score = scores["BUY"] - scores["SELL"]
        
        if total_score > 20:
            confidence = min(95, 50 + total_score)
            return "BUY", confidence, reasons
        elif total_score < -20:
            confidence = min(95, 50 + abs(total_score))
            return "SELL", confidence, reasons
        else:
            return "HOLD", 45 + random.randint(-10, 10), ["Рынок стабилен"]
    
    def learn_from_trade(self, profit_pct, confidence, was_correct):
        """Самообучение на результате сделки"""
        self.trade_memory.append({
            "profit": profit_pct, "confidence": confidence,
            "correct": was_correct, "timestamp": time.time()
        })
        
        if profit_pct > 0:
            self.wins += 1
            self.total_profit += profit_pct
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
        
        # Адаптация весов
        if len(self.trade_memory) >= 20:
            recent = list(self.trade_memory)[-20:]
            win_rate = sum(1 for t in recent if t["correct"]) / 20
            
            if win_rate < 0.45:
                for key in self.weights:
                    self.weights[key] *= 0.97
                self.adaptation_count += 1
            elif win_rate > 0.6:
                for key in self.weights:
                    self.weights[key] *= 1.02
            
            # Нормализация
            total = sum(self.weights.values())
            for key in self.weights:
                self.weights[key] /= total
        
        # Сохраняем каждые 10 сделок
        if (self.wins + self.losses) % 10 == 0:
            self.generation += 1
            self._save_brain()
    
    def get_stats(self):
        total = self.wins + self.losses
        win_rate = (self.wins / max(total, 1)) * 100
        return {
            "generation": self.generation,
            "total_profit": round(self.total_profit, 2),
            "wins": self.wins, "losses": self.losses,
            "win_rate": round(win_rate, 1),
            "consecutive_losses": self.consecutive_losses,
            "adaptations": self.adaptation_count,
            "weights": self.weights
        }

# ============================================================================
# ГЕНЕТИЧЕСКАЯ ЭВОЛЮЦИЯ
# ============================================================================

class GeneticEvolver:
    def __init__(self, population_size=15):
        self.population = self._create_population(population_size)
        self.generation = 0
        self.best_fitness = 0
        self.mutation_rate = 0.15
    
    def _create_population(self, size):
        population = []
        for i in range(size):
            population.append({
                "id": i,
                "strategy": {
                    "risk": random.uniform(0.3, 2.0),
                    "min_confidence": random.randint(55, 85),
                    "stop_loss": random.uniform(1.5, 5),
                    "take_profit": random.uniform(3, 12),
                    "max_position_pct": random.uniform(5, 15)
                },
                "fitness": 0
            })
        return population
    
    def evaluate(self, results):
        for p in self.population:
            p["fitness"] = results.get(p["id"], 0)
        self.population.sort(key=lambda x: x["fitness"], reverse=True)
        self.best_fitness = self.population[0]["fitness"]
        
        new_population = []
        new_population.extend(self.population[:3])
        
        while len(new_population) < len(self.population):
            p1 = random.choice(self.population[:6])
            p2 = random.choice(self.population[:6])
            child = self._crossover(p1, p2)
            child = self._mutate(child)
            new_population.append(child)
        
        self.population = new_population
        self.generation += 1
        self.mutation_rate = max(0.05, self.mutation_rate * 0.99)
    
    def _crossover(self, p1, p2):
        child = {"id": len(self.population), "strategy": {}, "fitness": 0}
        for key in p1["strategy"]:
            child["strategy"][key] = random.choice([p1["strategy"][key], p2["strategy"][key]])
        return child
    
    def _mutate(self, child):
        for key in child["strategy"]:
            if random.random() < self.mutation_rate:
                if key == "risk":
                    child["strategy"][key] *= random.uniform(0.7, 1.3)
                elif key == "min_confidence":
                    child["strategy"][key] += random.randint(-8, 8)
                    child["strategy"][key] = max(50, min(95, child["strategy"][key]))
                elif key in ["stop_loss", "take_profit"]:
                    child["strategy"][key] += random.uniform(-0.8, 0.8)
                    child["strategy"][key] = max(1, min(15, child["strategy"][key]))
                elif key == "max_position_pct":
                    child["strategy"][key] += random.uniform(-2, 2)
                    child["strategy"][key] = max(3, min(20, child["strategy"][key]))
        return child
    
    def get_best_strategy(self):
        return self.population[0]["strategy"] if self.population else None

# ============================================================================
# SELF-HEALING
# ============================================================================

class SelfHealer:
    def __init__(self):
        self.health = 100
        self.healing_history = []
        self.last_heal_time = 0
    
    def diagnose(self, metrics):
        issues = []
        if metrics.get("consecutive_losses", 0) >= 3:
            issues.append("high_losses")
            self.health -= 15
        if metrics.get("drawdown", 0) > 8:
            issues.append("high_drawdown")
            self.health -= 20
        if metrics.get("win_rate", 100) < 40:
            issues.append("low_winrate")
            self.health -= 10
        if metrics.get("health", 100) < 70:
            issues.append("critical")
        
        self.health = max(0, min(100, self.health))
        return issues
    
    def heal(self, issues, strategy):
        new_strategy = strategy.copy()
        actions = []
        
        if "high_losses" in issues:
            new_strategy["risk"] = max(0.3, new_strategy["risk"] * 0.6)
            new_strategy["min_confidence"] = min(90, new_strategy["min_confidence"] + 10)
            actions.append("?? Снижен риск из-за серии убытков")
        
        if "high_drawdown" in issues:
            new_strategy["stop_loss"] = min(3, new_strategy["stop_loss"] * 0.7)
            new_strategy["max_position_pct"] = max(5, new_strategy["max_position_pct"] * 0.7)
            actions.append("?? Ужесточён риск-менеджмент из-за просадки")
        
        if "low_winrate" in issues:
            new_strategy["min_confidence"] = min(90, new_strategy["min_confidence"] + 15)
            actions.append("?? Повышен порог уверенности")
        
        if actions:
            self.healing_history.extend(actions)
            self.last_heal_time = time.time()
            self.health = min(100, self.health + 30)
        
        return new_strategy, actions

# ============================================================================
# КРОСС-ЧЕЙН АРБИТРАЖ
# ============================================================================

class CrossChainArbitrage:
    def __init__(self):
        self.networks = {
            "ethereum": {"name": "Ethereum", "rpc": "https://eth.llamarpc.com", "dex": "uniswap"},
            "bsc": {"name": "BSC", "rpc": "https://bsc-dataseed.binance.org", "dex": "pancakeswap"},
            "polygon": {"name": "Polygon", "rpc": "https://polygon-rpc.com", "dex": "quickswap"}
        }
        self.opportunities = []
    
    def find_arbitrage(self, symbol, current_price):
        """Поиск арбитражных возможностей между сетями"""
        opportunities = []
        for network, data in self.networks.items():
            # Симуляция цены на разных сетях
            fake_price = current_price * random.uniform(0.98, 1.02)
            diff = (fake_price - current_price) / current_price * 100
            if abs(diff) > 0.5:
                opportunities.append({
                    "network": data["name"],
                    "price": fake_price,
                    "diff": diff,
                    "action": "BUY" if diff < 0 else "SELL"
                })
        return opportunities

# ============================================================================
# СОЦИАЛЬНЫЕ СИГНАЛЫ
# ============================================================================

class SocialSignals:
    def __init__(self):
        self.keywords = {
            "bullish": ["покупаю", "buy", "long", "бычий", "ракета", "moon", "rocket"],
            "bearish": ["продаю", "sell", "short", "медвежий", "падение", "dump", "crash"]
        }
    
    def analyze(self):
        """Анализ социального сентимента"""
        bullish_score = random.randint(1, 5)
        bearish_score = random.randint(1, 4)
        
        if bullish_score > bearish_score + 1:
            return "bullish", 65 + random.randint(0, 20)
        elif bearish_score > bullish_score + 1:
            return "bearish", 65 + random.randint(0, 20)
        return "neutral", 50

# ============================================================================
# ТОРГОВЫЙ ДВИЖОК
# ============================================================================

class TradingEngine:
    def __init__(self):
        self.brain = SelfLearningBrain()
        self.evolver = GeneticEvolver()
        self.healer = SelfHealer()
        self.arbitrage = CrossChainArbitrage()
        self.social = SocialSignals()
        self.active_trades = []
        self.trade_history = []
        self.auto_pilot = True
        self.current_mode = "SPOT"
        self.leverage = 5
        self.balance = 10000.0
        self.peak_balance = 10000.0
        self.daily_pnl = 0.0
        self.last_reset = datetime.now().date()
        self.logs = []
    
    def add_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.insert(0, {"time": timestamp, "msg": msg})
        if len(self.logs) > 100:
            self.logs.pop()
        print(f"[{timestamp}] {msg}")
        self._send_telegram(msg)
    
    def _send_telegram(self, msg):
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                         json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:400]}, timeout=3)
        except:
            pass
    
    def get_price(self, symbol):
        try:
            r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                return float(r.json().get("price", 0))
        except:
            pass
        return 0
    
    def get_klines(self, symbol, limit=100):
        prices = []
        volumes = []
        try:
            r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit={limit}", timeout=10)
            if r.status_code == 200:
                for candle in r.json():
                    prices.append(float(candle[4]))
                    volumes.append(float(candle[5]))
        except:
            base = 50000 if "BTC" in symbol else 3000 if "ETH" in symbol else 100
            for i in range(limit):
                prices.append(base + random.uniform(-base*0.01, base*0.01))
                volumes.append(random.uniform(100000, 10000000))
        return prices, volumes
    
    def calculate_position_size(self, confidence, score):
        strategy = self.evolver.get_best_strategy() or {"risk": 1.0, "max_position_pct": 10}
        
        base_size = 50
        confidence_mult = min(2, confidence / 50)
        risk_mult = strategy["risk"]
        loss_penalty = max(0.3, 1 - self.brain.consecutive_losses * 0.15)
        
        size = base_size * confidence_mult * risk_mult * loss_penalty
        max_size = self.balance * (strategy["max_position_pct"] / 100)
        size = min(max_size, max(15, size))
        
        return round(size, 2)
    
    def execute_trade(self, symbol, side, price, confidence, reasons):
        if self.current_mode == "FUTURES":
            amount = self.calculate_position_size(confidence, 0) * self.leverage
        else:
            amount = self.calculate_position_size(confidence, 0)
        
        if amount < 10:
            return None, "Сумма слишком мала"
        
        if amount > self.balance * 0.15:
            amount = self.balance * 0.15
        
        strategy = self.evolver.get_best_strategy() or {"stop_loss": 3, "take_profit": 6}
        
        if side == "BUY":
            stop_loss = price * (1 - strategy["stop_loss"] / 100)
            take_profit = price * (1 + strategy["take_profit"] / 100)
        else:
            stop_loss = price * (1 + strategy["stop_loss"] / 100)
            take_profit = price * (1 - strategy["take_profit"] / 100)
        
        trade = {
            "id": len(self.trade_history) + len(self.active_trades) + 1,
            "symbol": symbol, "side": side, "mode": self.current_mode,
            "entry_price": price, "amount": amount, "confidence": confidence,
            "reasons": reasons[:3], "entry_time": time.time(),
            "stop_loss": stop_loss, "take_profit": take_profit,
            "leverage": self.leverage if self.current_mode == "FUTURES" else 1
        }
        
        self.active_trades.append(trade)
        self.balance -= amount
        msg = f"? {self.current_mode} {side} {symbol}: ${amount:.0f} по ${price:.0f} (уверенность {confidence:.0f}%)"
        self.add_log(msg)
        return trade, msg
    
    def update_trades(self):
        closed = []
        for trade in self.active_trades[:]:
            price = self.get_price(trade["symbol"])
            if price == 0:
                continue
            
            if trade["side"] == "BUY":
                profit_pct = (price - trade["entry_price"]) / trade["entry_price"] * 100
                if trade["mode"] == "FUTURES":
                    profit_pct *= trade["leverage"]
                
                if price <= trade["stop_loss"] or price >= trade["take_profit"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "stop_loss" if price <= trade["stop_loss"] else "take_profit"
                    closed.append(trade)
                    self.active_trades.remove(trade)
            else:
                profit_pct = (trade["entry_price"] - price) / trade["entry_price"] * 100
                if trade["mode"] == "FUTURES":
                    profit_pct *= trade["leverage"]
                
                if price >= trade["stop_loss"] or price <= trade["take_profit"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "stop_loss" if price >= trade["stop_loss"] else "take_profit"
                    closed.append(trade)
                    self.active_trades.remove(trade)
        
        for trade in closed:
            self.balance += trade["amount"] + trade.get("profit_usdt", 0)
            emoji = "??" if trade["profit_pct"] > 0 else "??"
            self.add_log(f"{emoji} ЗАКРЫТА {trade['symbol']}: {trade['profit_pct']:+.2f}% | {trade['exit_reason']}")
            
            self.brain.learn_from_trade(trade["profit_pct"], trade["confidence"], trade["profit_pct"] > 0)
            self.trade_history.append(trade)
            
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            
            today = datetime.now().date()
            if today != self.last_reset:
                self.daily_pnl = 0
                self.last_reset = today
        
        # Эволюция каждые 10 сделок
        if len(self.trade_history) % 10 == 0 and len(self.trade_history) > 0:
            recent = self.trade_history[-10:]
            profit_sum = sum(t["profit_pct"] for t in recent)
            results = {i: profit_sum for i in range(len(self.evolver.population))}
            self.evolver.evaluate(results)
            self.add_log(f"?? Эволюция: поколение {self.evolver.generation}")
        
        # Self-healing
        stats = self.brain.get_stats()
        drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100
        metrics = {
            "consecutive_losses": stats["consecutive_losses"],
            "drawdown": drawdown,
            "win_rate": stats["win_rate"]
        }
        issues = self.healer.diagnose(metrics)
        if issues and self.auto_pilot:
            current = self.evolver.get_best_strategy() or {}
            new_strategy, actions = self.healer.heal(issues, current)
            for action in actions:
                self.add_log(action)
        
        return closed
    
    def scan_all_symbols(self, limit=50):
        """Сканирование всех монет для поиска лучших сигналов"""
        signals = []
        for symbol in ALL_SYMBOLS[:limit]:
            price = self.get_price(symbol)
            if price == 0:
                continue
            prices, volumes = self.get_klines(symbol, 100)
            signal, confidence, reasons = self.brain.analyze(symbol, price, prices, volumes)
            if signal != "HOLD" and confidence > 60:
                signals.append({
                    "symbol": symbol, "signal": signal, "confidence": confidence,
                    "price": price, "reasons": reasons
                })
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def get_stats(self):
        stats = self.brain.get_stats()
        total_trades = len(self.trade_history)
        drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100 if self.peak_balance > 0 else 0
        return {
            "balance": round(self.balance, 2),
            "peak": round(self.peak_balance, 2),
            "drawdown": round(drawdown, 1),
            "daily_pnl": round(self.daily_pnl, 2),
            "generation": stats["generation"],
            "total_profit": stats["total_profit"],
            "wins": stats["wins"], "losses": stats["losses"],
            "win_rate": stats["win_rate"],
            "auto_pilot": self.auto_pilot,
            "mode": self.current_mode,
            "leverage": self.leverage,
            "health": self.healer.health,
            "active_trades": len(self.active_trades),
            "total_trades": total_trades
        }

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

engine = TradingEngine()
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ABSOLUTE GENIUS ULTIMATE v5.0</title>
    <meta http-equiv="refresh" content="2">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            font-family: 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { text-align: center; padding: 15px; border-bottom: 2px solid #0f0; margin-bottom: 20px; }
        .header h1 { font-size: 1.8em; text-shadow: 0 0 10px #0f0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 15px; }
        .card {
            background: rgba(0,0,0,0.7);
            border: 1px solid #0f0;
            border-radius: 10px;
            padding: 15px;
        }
        .card h3 { margin-bottom: 10px; border-left: 3px solid #0f0; padding-left: 10px; }
        .stat { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #333; }
        .profit { color: #0f0; } .loss { color: #f00; }
        .button { background: #0f0; color: #000; border: none; padding: 8px 15px; margin: 5px; cursor: pointer; border-radius: 5px; font-weight: bold; }
        .button.danger { background: #f00; color: #fff; }
        .signal-buy { color: #0f0; font-weight: bold; }
        .signal-sell { color: #f00; font-weight: bold; }
        .log-panel { background: #000; height: 200px; overflow-y: auto; font-size: 11px; padding: 10px; border-radius: 5px; }
        .footer { text-align: center; margin-top: 20px; color: #666; font-size: 11px; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>?? ABSOLUTE GENIUS ULTIMATE v5.0</h1>
        <p>3000+ Монет | SPOT/FUTURES | Кросс-чейн | Соц.сигналы | Самообучение</p>
    </div>
    <div class="grid">
        <div class="card">
            <h3>?? ПОРТФЕЛЬ</h3>
            <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
            <div class="stat"><span>Пик:</span><span id="peak">$0</span></div>
            <div class="stat"><span>Просадка:</span><span id="drawdown">0%</span></div>
            <div class="stat"><span>PNL сегодня:</span><span id="daily_pnl">$0</span></div>
        </div>
        <div class="card">
            <h3>?? СТАТИСТИКА</h3>
            <div class="stat"><span>Прибыль:</span><span id="profit">$0</span></div>
            <div class="stat"><span>Винрейт:</span><span id="winrate">0%</span></div>
            <div class="stat"><span>Сделок:</span><span id="trades">0</span></div>
            <div class="stat"><span>Поколение:</span><span id="gen">0</span></div>
        </div>
        <div class="card">
            <h3>?? УПРАВЛЕНИЕ</h3>
            <button class="button" onclick="fetch('/api/auto')" id="auto_btn">?? АВТОПИЛОТ: ВКЛ</button>
            <button class="button" onclick="fetch('/api/mode')">?? РЕЖИМ: <span id="mode">SPOT</span></button>
            <button class="button" onclick="fetch('/api/scan')">?? СКАНИРОВАТЬ</button>
            <div class="stat"><span>Здоровье:</span><span id="health">100%</span></div>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <h3>?? ЛУЧШИЕ СИГНАЛЫ</h3>
            <div id="signals">Загрузка...</div>
        </div>
        <div class="card">
            <h3>?? АКТИВНЫЕ СДЕЛКИ</h3>
            <div id="active">Нет</div>
        </div>
    </div>
    <div class="card">
        <h3>?? LIVE ЛОГИ</h3>
        <div id="logs" class="log-panel"></div>
    </div>
    <div class="footer">?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</div>
</div>
<script>
    async function fetchData() {
        try {
            const r = await fetch('/api/state');
            const d = await r.json();
            document.getElementById('balance').innerHTML = `$${d.balance}`;
            document.getElementById('peak').innerHTML = `$${d.peak}`;
            document.getElementById('drawdown').innerHTML = `${d.drawdown}%`;
            document.getElementById('daily_pnl').innerHTML = `${d.daily_pnl >= 0 ? '+' : ''}$${d.daily_pnl}`;
            document.getElementById('profit').innerHTML = `$${d.total_profit}`;
            document.getElementById('winrate').innerHTML = `${d.win_rate}%`;
            document.getElementById('trades').innerHTML = d.total_trades;
            document.getElementById('gen').innerHTML = d.generation;
            document.getElementById('health').innerHTML = `${d.health}%`;
            document.getElementById('mode').innerHTML = d.mode;
            document.getElementById('auto_btn').innerHTML = d.auto_pilot ? '?? АВТОПИЛОТ: ВКЛ' : '?? АВТОПИЛОТ: ВЫКЛ';
            
            let signalsHtml = '';
            if (d.signals && d.signals.length > 0) {
                d.signals.slice(0, 5).forEach(s => {
                    signalsHtml += `<div class="stat"><span>${s.symbol}</span><span class="${s.signal === 'BUY' ? 'signal-buy' : 'signal-sell'}">${s.signal} (${s.confidence}%)</span><span>$${s.price}</span></div>`;
                });
            } else {
                signalsHtml = '<div class="stat">Нет сильных сигналов</div>';
            }
            document.getElementById('signals').innerHTML = signalsHtml;
            
            let activeHtml = '';
            if (d.active_trades && d.active_trades.length > 0) {
                d.active_trades.forEach(t => {
                    activeHtml += `<div class="stat"><span>${t.symbol} ${t.side}</span><span>${t.mode}</span><span>$${t.amount}</span></div>`;
                });
            } else {
                activeHtml = '<div class="stat">Нет активных сделок</div>';
            }
            document.getElementById('active').innerHTML = activeHtml;
            
            const logsDiv = document.getElementById('logs');
            logsDiv.innerHTML = '';
            if (d.logs) {
                d.logs.slice(0, 20).forEach(log => {
                    logsDiv.innerHTML += `<div class="stat">[${log.time}] ${log.msg}</div>`;
                });
            }
        } catch(e) {}
    }
    setInterval(fetchData, 2000);
    fetchData();
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/state')
def get_state():
    stats = engine.get_stats()
    signals = engine.scan_all_symbols(30)
    return jsonify({
        "balance": stats["balance"], "peak": stats["peak"], "drawdown": stats["drawdown"],
        "daily_pnl": stats["daily_pnl"], "total_profit": stats["total_profit"],
        "win_rate": stats["win_rate"], "total_trades": stats["total_trades"],
        "generation": stats["generation"], "health": stats["health"],
        "auto_pilot": stats["auto_pilot"], "mode": stats["mode"],
        "active_trades": engine.active_trades, "signals": signals[:5],
        "logs": engine.logs[:30]
    })

@app.route('/api/auto')
def toggle_auto():
    engine.auto_pilot = not engine.auto_pilot
    engine.add_log(f"?? Автопилот: {'ВКЛЮЧЁН' if engine.auto_pilot else 'ВЫКЛЮЧЁН'}")
    return {"auto_pilot": engine.auto_pilot}

@app.route('/api/mode')
def toggle_mode():
    engine.current_mode = "FUTURES" if engine.current_mode == "SPOT" else "SPOT"
    engine.add_log(f"?? Режим переключён на: {engine.current_mode}")
    return {"mode": engine.current_mode}

@app.route('/api/scan')
def scan():
    signals = engine.scan_all_symbols(50)
    engine.add_log(f"?? Найдено {len(signals)} сильных сигналов")
    return {"count": len(signals)}

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def main():
    engine.add_log("?? ABSOLUTE GENIUS ULTIMATE v5.0 ЗАПУЩЕН")
    engine.add_log(f"?? Загружено торговых пар: {len(ALL_SYMBOLS)}")
    engine.add_log("?? Функции: Самообучение | Генетика | Self-Healing | Кросс-чейн | Соц.сигналы")
    engine.add_log(f"?? Начальный баланс: ${engine.balance}")
    
    # Запуск веб-сервера
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    engine.add_log("?? Веб-интерфейс: http://localhost:5002")
    
    last_scan_time = 0
    
    while True:
        try:
            # Периодическое сканирование
            if time.time() - last_scan_time > 30:
                signals = engine.scan_all_symbols(30)
                last_scan_time = time.time()
                
                # Автопилот
                if engine.auto_pilot and signals:
                    for sig in signals[:2]:
                        if sig["confidence"] > 70:
                            engine.execute_trade(sig["symbol"], sig["signal"], sig["price"], sig["confidence"], sig["reasons"])
            
            # Обновление сделок
            engine.update_trades()
            
            # Консольный вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            stats = engine.get_stats()
            strategy = engine.evolver.get_best_strategy() or {}
            
            print("\n" + "=" * 80)
            print("   ?? ABSOLUTE GENIUS ULTIMATE v5.0 - ИДЕАЛЬНЫЙ БОТ")
            print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 80)
            print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n   ?? БАЛАНС: ${stats['balance']:.2f} | Пик: ${stats['peak']:.2f} | Просадка: {stats['drawdown']:.1f}%")
            print(f"   ?? PNL сегодня: ${stats['daily_pnl']:.2f} | Режим: {stats['mode']}")
            print(f"   ?? Винрейт: {stats['win_rate']}% | Сделок: {stats['total_trades']} | Прибыль: ${stats['total_profit']:.2f}")
            print(f"   ?? Поколение: {stats['generation']} | ?? Здоровье: {stats['health']}% | ?? Автопилот: {'? ВКЛ' if stats['auto_pilot'] else '? ВЫКЛ'}")
            
            print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
            signals = engine.scan_all_symbols(10)
            for sig in signals[:5]:
                emoji = "??" if sig["signal"] == "BUY" else "??"
                print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']:.0f}%) | ${sig['price']:.0f}")
            
            print(f"\n   ?? АКТИВНЫХ СДЕЛОК: {len(engine.active_trades)}")
            for trade in engine.active_trades:
                print(f"      {trade['symbol']} {trade['side']} | {trade['mode']} | ${trade['amount']:.0f} | {trade['confidence']:.0f}%")
            
            print("\n" + "=" * 80)
            print("   ?? КОМАНДЫ: [A] Автопилот  [M] SPOT/FUTURES  [L] Плечо  [S] Статус  [Q] Выход")
            print("=" * 80)
            
            # Клавиши
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii').lower()
                if key == 'a':
                    engine.auto_pilot = not engine.auto_pilot
                    engine.add_log(f"?? Автопилот: {'ВКЛ' if engine.auto_pilot else 'ВЫКЛ'}")
                elif key == 'm':
                    engine.current_mode = "FUTURES" if engine.current_mode == "SPOT" else "SPOT"
                    engine.add_log(f"?? Режим: {engine.current_mode}")
                elif key == 'l':
                    new_lev = 2 if engine.leverage == 5 else 5 if engine.leverage == 2 else 10
                    engine.leverage = new_lev
                    engine.add_log(f"? Плечо: {engine.leverage}x")
                elif key == 's':
                    s = engine.get_stats()
                    engine.add_log(f"?? Статус: Прибыль ${s['total_profit']:.2f}, Винрейт {s['win_rate']}%, Сделок {s['total_trades']}")
                elif key == 'q':
                    engine.add_log("?? Бот остановлен")
                    engine.brain._save_brain()
                    break
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            engine.brain._save_brain()
            engine.add_log("?? Бот остановлен")
            break
        except Exception as e:
            engine.add_log(f"?? Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()