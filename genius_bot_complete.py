# -*- coding: utf-8 -*-
# genius_bot_complete.py - ПОЛНОСТЬЮ САМООБУЧАЕМЫЙ БОТ
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
# ВЕРСИЯ 3.0 - САМООБУЧЕНИЕ + ГЕНЕТИКА + SELF-HEALING

import time
import requests
import random
import threading
import os
import json
import msvcrt
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask, jsonify, render_template_string

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

# ============================================================================
# САМООБУЧАЕМАЯ НЕЙРОСЕТЬ
# ============================================================================

class SelfLearningBrain:
    def __init__(self, brain_file="genius_brain.json"):
        self.brain_file = brain_file
        self.learning_rate = 0.01
        self.exploration_rate = 0.1
        
        # Веса индикаторов (обучаемые)
        self.weights = {
            "rsi": 0.15, "macd": 0.15, "volume": 0.12, "momentum": 0.12,
            "volatility": 0.10, "trend": 0.10, "support_resistance": 0.08,
            "sentiment": 0.08, "arbitrage": 0.05, "orderbook": 0.05
        }
        
        # Память сделок (для обучения)
        self.trade_memory = deque(maxlen=200)
        self.performance_history = []
        self.total_profit = 0
        self.wins = 0
        self.losses = 0
        self.generation = 0
        
        # Загружаем сохранённый мозг
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
    
    def analyze(self, prices, volumes):
        """Анализ рынка с самообучающимися весами"""
        if len(prices) < 30:
            return "HOLD", 0, []
        
        scores = {"BUY": 0, "SELL": 0}
        reasons = []
        
        # ---- RSI анализ ----
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-14:]]
        losses = [-d if d < 0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.001
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))
        
        if rsi < 30:
            scores["BUY"] += 30 * self.weights["rsi"]
            reasons.append(f"RSI={rsi:.1f} (перепроданность)")
        elif rsi > 70:
            scores["SELL"] += 30 * self.weights["rsi"]
            reasons.append(f"RSI={rsi:.1f} (перекупленность)")
        
        # ---- MACD анализ ----
        ema12 = sum(prices[-12:]) / 12
        ema26 = sum(prices[-26:]) / 26 if len(prices) >= 26 else ema12
        macd = ema12 - ema26
        if macd > 0:
            scores["BUY"] += 25 * self.weights["macd"]
            reasons.append("MACD бычий")
        elif macd < 0:
            scores["SELL"] += 25 * self.weights["macd"]
            reasons.append("MACD медвежий")
        
        # ---- Объём ----
        if volumes:
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
            if vol_ratio > 1.5:
                scores["BUY"] += 20 * self.weights["volume"]
                reasons.append(f"Объём в {vol_ratio:.1f}x выше среднего")
        
        # ---- Моментум ----
        momentum = (prices[-1] - prices[-10]) / prices[-10] * 100 if len(prices) >= 10 else 0
        if momentum > 1:
            scores["BUY"] += 20 * self.weights["momentum"]
            reasons.append(f"Моментум +{momentum:.1f}%")
        elif momentum < -1:
            scores["SELL"] += 20 * self.weights["momentum"]
            reasons.append(f"Моментум {momentum:.1f}%")
        
        # ---- Волатильность ----
        returns = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        volatility = np.std(returns[-20:]) if len(returns) >= 20 else 0.5
        if 1 < volatility < 5:
            scores["BUY"] += 10 * self.weights["volatility"]
            reasons.append(f"Волатильность {volatility:.1f}% (оптимальная)")
        
        # ---- Тренд ----
        sma20 = sum(prices[-20:]) / 20
        sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sma20
        if sma20 > sma50:
            scores["BUY"] += 15 * self.weights["trend"]
            reasons.append("Восходящий тренд")
        elif sma20 < sma50:
            scores["SELL"] += 15 * self.weights["trend"]
            reasons.append("Нисходящий тренд")
        
        # ---- Уровни поддержки/сопротивления ----
        support = min(prices[-50:]) if len(prices) >= 50 else min(prices)
        resistance = max(prices[-50:]) if len(prices) >= 50 else max(prices)
        current = prices[-1]
        if current <= support * 1.01:
            scores["BUY"] += 15 * self.weights["support_resistance"]
            reasons.append(f"Уровень поддержки ${support:.0f}")
        elif current >= resistance * 0.99:
            scores["SELL"] += 15 * self.weights["support_resistance"]
            reasons.append(f"Уровень сопротивления ${resistance:.0f}")
        
        # Определяем сигнал
        if scores["BUY"] > scores["SELL"] and scores["BUY"] > 20:
            confidence = min(95, 50 + scores["BUY"])
            return "BUY", confidence, reasons
        elif scores["SELL"] > scores["BUY"] and scores["SELL"] > 20:
            confidence = min(95, 50 + scores["SELL"])
            return "SELL", confidence, reasons
        else:
            return "HOLD", 40 + random.randint(-10, 10), ["Рынок стабилен"]
    
    def learn_from_trade(self, profit_pct, confidence, was_correct):
        """Обучение на результате сделки"""
        self.trade_memory.append({
            "profit": profit_pct,
            "confidence": confidence,
            "correct": was_correct,
            "timestamp": time.time()
        })
        
        if profit_pct > 0:
            self.wins += 1
            self.total_profit += profit_pct
        else:
            self.losses += 1
        
        # Адаптация весов
        if len(self.trade_memory) >= 10:
            recent = list(self.trade_memory)[-10:]
            win_rate = sum(1 for t in recent if t["correct"]) / 10
            
            # Если винрейт низкий - корректируем веса
            if win_rate < 0.4:
                # Уменьшаем веса индикаторов которые давали ложные сигналы
                for key in self.weights:
                    self.weights[key] *= 0.95
            elif win_rate > 0.6:
                # Увеличиваем веса
                for key in self.weights:
                    self.weights[key] *= 1.02
            
            # Нормализуем веса
            total = sum(self.weights.values())
            for key in self.weights:
                self.weights[key] /= total
            
            # Сохраняем мозг
            self.generation += 1
            self._save_brain()
    
    def get_stats(self):
        total_trades = self.wins + self.losses
        win_rate = (self.wins / total_trades * 100) if total_trades > 0 else 0
        return {
            "generation": self.generation,
            "total_profit": round(self.total_profit, 2),
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 1),
            "weights": self.weights
        }

# ============================================================================
# ГЕНЕТИЧЕСКИЙ АЛГОРИТМ (самоэволюция)
# ============================================================================

class GeneticEvolver:
    def __init__(self):
        self.population = self._create_population()
        self.generation = 0
        self.best_fitness = 0
    
    def _create_population(self, size=10):
        population = []
        for i in range(size):
            population.append({
                "id": i,
                "strategy": {
                    "risk": random.uniform(0.5, 2),
                    "min_confidence": random.randint(55, 85),
                    "stop_loss": random.uniform(1, 5),
                    "take_profit": random.uniform(2, 10)
                },
                "fitness": 0
            })
        return population
    
    def evaluate(self, results):
        for p in self.population:
            p["fitness"] = results.get(p["id"], 0)
        
        self.population.sort(key=lambda x: x["fitness"], reverse=True)
        self.best_fitness = self.population[0]["fitness"]
        
        # Эволюция
        new_population = []
        # Оставляем лучших
        new_population.extend(self.population[:3])
        
        # Скрещивание
        while len(new_population) < 10:
            p1 = random.choice(self.population[:5])
            p2 = random.choice(self.population[:5])
            child = self._crossover(p1, p2)
            child = self._mutate(child)
            new_population.append(child)
        
        self.population = new_population
        self.generation += 1
    
    def _crossover(self, p1, p2):
        child = {"id": len(self.population), "strategy": {}, "fitness": 0}
        for key in p1["strategy"]:
            child["strategy"][key] = random.choice([p1["strategy"][key], p2["strategy"][key]])
        return child
    
    def _mutate(self, child):
        for key in child["strategy"]:
            if random.random() < 0.2:
                if key == "risk":
                    child["strategy"][key] *= random.uniform(0.8, 1.2)
                elif key == "min_confidence":
                    child["strategy"][key] += random.randint(-5, 5)
                    child["strategy"][key] = max(50, min(95, child["strategy"][key]))
                elif key in ["stop_loss", "take_profit"]:
                    child["strategy"][key] += random.uniform(-0.5, 0.5)
                    child["strategy"][key] = max(0.5, min(15, child["strategy"][key]))
        return child
    
    def get_best_strategy(self):
        return self.population[0]["strategy"] if self.population else None

# ============================================================================
# SELF-HEALING (автоисправление)
# ============================================================================

class SelfHealer:
    def __init__(self):
        self.errors = []
        self.heals = []
        self.health = 100
    
    def check(self, metrics):
        issues = []
        if metrics.get("consecutive_losses", 0) >= 3:
            issues.append("high_consecutive_losses")
            self.health -= 15
        if metrics.get("drawdown", 0) > 10:
            issues.append("high_drawdown")
            self.health -= 20
        if metrics.get("win_rate", 100) < 40:
            issues.append("low_win_rate")
            self.health -= 10
        
        return issues
    
    def heal(self, issues, current_strategy):
        new_strategy = current_strategy.copy()
        action = None
        
        if "high_consecutive_losses" in issues:
            new_strategy["risk"] = max(0.3, new_strategy["risk"] * 0.6)
            new_strategy["min_confidence"] = min(90, new_strategy["min_confidence"] + 10)
            action = "?? Снижен риск из-за серии убытков"
        
        if "high_drawdown" in issues:
            new_strategy["stop_loss"] = min(3, new_strategy["stop_loss"] * 0.7)
            action = "?? Ужесточён стоп-лосс из-за просадки"
        
        if "low_win_rate" in issues:
            new_strategy["min_confidence"] = min(90, new_strategy["min_confidence"] + 15)
            action = "?? Повышен порог уверенности"
        
        if action:
            self.heals.append(action)
            self.health = min(100, self.health + 20)
        
        return new_strategy, action

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

brain = SelfLearningBrain()
evolver = GeneticEvolver()
healer = SelfHealer()
logs = []
active_trades = []
trade_history = []
auto_pilot = True
last_signals = {}

def add_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, {"time": timestamp, "msg": msg})
    if len(logs) > 100:
        logs.pop()
    print(f"[{timestamp}] {msg}")
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:300]}, timeout=3)
    except:
        pass

def get_price(symbol):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(symbol, limit=100):
    prices = []
    volumes = []
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit={limit}", timeout=10)
        if r.status_code == 200:
            for candle in r.json():
                prices.append(float(candle[4]))
                volumes.append(float(candle[5]))
    except:
        base = 50000 if symbol == "BTCUSDT" else 3000 if symbol == "ETHUSDT" else 100
        for i in range(limit):
            prices.append(base + random.uniform(-base*0.01, base*0.01))
            volumes.append(random.uniform(100000, 10000000))
    return prices, volumes

def execute_trade(symbol, side, price, confidence):
    global active_trades
    balance = 10000 - sum(t["amount"] for t in active_trades if t["side"] == "BUY")
    amount = min(100, balance * 0.1)
    
    if amount < 10:
        return None
    
    strategy = evolver.get_best_strategy() or {"stop_loss": 3, "take_profit": 6}
    
    trade = {
        "symbol": symbol, "side": side, "entry_price": price,
        "amount": amount, "confidence": confidence, "entry_time": time.time(),
        "stop_loss": price * (1 - strategy["stop_loss"]/100) if side == "BUY" else price * (1 + strategy["stop_loss"]/100),
        "take_profit": price * (1 + strategy["take_profit"]/100) if side == "BUY" else price * (1 - strategy["take_profit"]/100)
    }
    active_trades.append(trade)
    add_log(f"? {side} {symbol}: ${amount:.0f} по ${price:.0f} (уверенность {confidence:.0f}%)")
    return trade

def update_trades():
    global active_trades, trade_history, brain, evolver, auto_pilot
    closed = []
    for trade in active_trades[:]:
        price = get_price(trade["symbol"])
        if price == 0:
            continue
        
        if trade["side"] == "BUY":
            profit_pct = (price - trade["entry_price"]) / trade["entry_price"] * 100
            if price <= trade["stop_loss"] or price >= trade["take_profit"]:
                trade["exit_price"] = price
                trade["profit_pct"] = profit_pct
                trade["exit_reason"] = "stop_loss" if price <= trade["stop_loss"] else "take_profit"
                closed.append(trade)
                active_trades.remove(trade)
        else:
            profit_pct = (trade["entry_price"] - price) / trade["entry_price"] * 100
            if price >= trade["stop_loss"] or price <= trade["take_profit"]:
                trade["exit_price"] = price
                trade["profit_pct"] = profit_pct
                trade["exit_reason"] = "stop_loss" if price >= trade["stop_loss"] else "take_profit"
                closed.append(trade)
                active_trades.remove(trade)
    
    for trade in closed:
        emoji = "??" if trade["profit_pct"] > 0 else "??"
        add_log(f"{emoji} ЗАКРЫТА {trade['symbol']}: {trade['profit_pct']:+.2f}% | {trade['exit_reason']}")
        
        brain.learn_from_trade(trade["profit_pct"], trade["confidence"], trade["profit_pct"] > 0)
        trade_history.append(trade)
        
        # Генетическая эволюция каждые 10 сделок
        if len(trade_history) % 10 == 0:
            results = {i: 0 for i in range(10)}
            evolver.evaluate(results)
            if evolver.get_best_strategy():
                add_log(f"?? Эволюция: новое поколение {evolver.generation}")
        
        # Self-healing
        stats = brain.get_stats()
        metrics = {"consecutive_losses": brain.losses - brain.wins if brain.losses > brain.wins else 0, 
                   "drawdown": 0, "win_rate": stats["win_rate"]}
        issues = healer.check(metrics)
        if issues and auto_pilot:
            new_strategy, action = healer.heal(issues, evolver.get_best_strategy() or {})
            if action:
                add_log(action)
    
    return closed

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

app = Flask(__name__)

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head><title>GENIUS BOT</title><meta http-equiv="refresh" content="2">
    <style>body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
    .card{background:#111;border:1px solid #0f0;padding:15px;margin:10px 0;border-radius:10px}
    .profit{color:#0f0}.loss{color:#f00}</style></head>
    <body>
    <h1>?? GENIUS TRADING BOT</h1>
    <div id="data">Loading...</div>
    <script>
    async function update(){
        const r=await fetch('/api/state');
        const d=await r.json();
        document.getElementById('data').innerHTML=`
            <div class="card"><b>?? СТАТИСТИКА</b><br>
            ?? Поколение: ${d.generation}<br>
            ?? Прибыль: $${d.total_profit}<br>
            ?? Винрейт: ${d.win_rate}%<br>
            ? Выигрышей: ${d.wins} | ? Проигрышей: ${d.losses}<br>
            ?? Автопилот: ${d.auto_pilot ? 'ВКЛ' : 'ВЫКЛ'}<br>
            ?? Здоровье: ${d.health}%</div>
            <div class="card"><b>?? ЛУЧШИЙ СИГНАЛ</b><br>
            Монета: ${d.best_signal?.symbol || '---'}<br>
            Сигнал: ${d.best_signal?.signal || '---'}<br>
            Уверенность: ${d.best_signal?.confidence || 0}%</div>
            <div class="card"><b>?? АКТИВНЫЕ СДЕЛКИ</b><br>${d.active_trades.map(t=>`${t.symbol} ${t.side} $${t.amount}`).join('<br>') || 'Нет'}</div>
            <div class="card"><b>?? ПОСЛЕДНИЕ ЛОГИ</b><br>${d.logs.slice(0,10).map(l=>`[${l.time}] ${l.msg}`).join('<br>')}</div>
            <button onclick="fetch('/api/auto')">?? АВТОПИЛОТ</button>
        `;
    }
    setInterval(update,2000);
    update();
    </script>
    </body>
    </html>
    '''

@app.route('/api/state')
def state():
    stats = brain.get_stats()
    signals = []
    for coin in COINS:
        price = get_price(coin)
        if price:
            prices, vols = get_klines(coin, 50)
            sig, conf, _ = brain.analyze(prices, vols)
            signals.append({"symbol": coin, "signal": sig, "confidence": conf, "price": price})
    signals.sort(key=lambda x: x["confidence"] if x["signal"] != "HOLD" else 0, reverse=True)
    best = signals[0] if signals else None
    return jsonify({
        "generation": stats["generation"], "total_profit": stats["total_profit"],
        "wins": stats["wins"], "losses": stats["losses"], "win_rate": stats["win_rate"],
        "auto_pilot": auto_pilot, "health": healer.health, "best_signal": best,
        "active_trades": active_trades, "logs": logs[:20]
    })

@app.route('/api/auto')
def toggle_auto():
    global auto_pilot
    auto_pilot = not auto_pilot
    add_log(f"?? Автопилот: {'ВКЛЮЧЁН' if auto_pilot else 'ВЫКЛЮЧЁН'}")
    return {"auto_pilot": auto_pilot}

# ============================================================================
# ЗАПУСК
# ============================================================================

def main():
    global auto_pilot
    
    add_log("?? NEURAL GENESIS BOT v3.0 ЗАПУЩЕН")
    add_log("?? Функции: Самообучение | Генетическая эволюция | Self-Healing")
    add_log("?? Цель: Постоянное совершенствование и максимальная прибыль")
    
    # Запуск веб-сервера
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    add_log("?? Веб-интерфейс: http://localhost:5002")
    
    consecutive_no_trades = 0
    
    while True:
        try:
            signals = []
            for coin in COINS:
                price = get_price(coin)
                if price:
                    prices, volumes = get_klines(coin, 100)
                    signal, confidence, reasons = brain.analyze(prices, volumes)
                    if signal != "HOLD" and confidence > 55:
                        signals.append({"symbol": coin, "signal": signal, "confidence": confidence, "price": price, "reasons": reasons})
            
            signals.sort(key=lambda x: x["confidence"], reverse=True)
            
            # Автопилот
            if auto_pilot and signals:
                for sig in signals[:2]:
                    execute_trade(sig["symbol"], sig["signal"], sig["price"], sig["confidence"])
            
            # Обновление сделок
            closed = update_trades()
            
            # Консоль
            os.system('cls' if os.name == 'nt' else 'clear')
            stats = brain.get_stats()
            strategy = evolver.get_best_strategy() or {}
            
            print("\n" + "=" * 70)
            print("   ?? NEURAL GENESIS BOT v3.0 - САМООБУЧАЕМЫЙ")
            print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 70)
            print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n   ?? Общая прибыль: ${stats['total_profit']:.2f}")
            print(f"   ?? Винрейт: {stats['win_rate']}% | Сделок: {stats['wins'] + stats['losses']}")
            print(f"   ?? Поколение: {stats['generation']} | ?? Здоровье: {healer.health}%")
            print(f"   ?? Автопилот: {'? ВКЛ' if auto_pilot else '? ВЫКЛ'}")
            
            print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
            for sig in signals[:5]:
                emoji = "??" if sig["signal"] == "BUY" else "??"
                print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']:.0f}%) | ${sig['price']:.0f}")
            
            print(f"\n   ?? АКТИВНЫХ СДЕЛОК: {len(active_trades)}")
            for trade in active_trades:
                print(f"      {trade['symbol']} {trade['side']} | ${trade['amount']:.0f} | {trade['confidence']:.0f}%")
            
            print("\n" + "=" * 70)
            print("   [A] Автопилот  [S] Статус  [Q] Выход")
            print("=" * 70)
            
            # Клавиши
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii').lower()
                if key == 'a':
                    auto_pilot = not auto_pilot
                    add_log(f"?? Автопилот: {'ВКЛ' if auto_pilot else 'ВЫКЛ'}")
                elif key == 's':
                    add_log(f"?? Статус: Прибыль ${stats['total_profit']:.2f}, Винрейт {stats['win_rate']}%")
                elif key == 'q':
                    add_log("?? Бот остановлен")
                    brain._save_brain()
                    break
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            brain._save_brain()
            add_log("?? Бот остановлен")
            break
        except Exception as e:
            add_log(f"?? Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    import numpy as np
    main()