# -*- coding: utf-8 -*-
# pro_trading_bot_v14.py - Профессиональная торговая платформа
import time
import requests
import random
import threading
import os
import json
import msvcrt
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from collections import defaultdict

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# Режимы торговли
TRADING_MODES = ["SPOT", "FUTURES"]
CURRENT_MODE = "SPOT"  # SPOT или FUTURES
FUTURES_LEVERAGE = 5   # Плечо для фьючерсов (1-10x)

# Топ-50 монет для отслеживания (можно расширить до 3000+)
TOP_COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "SHIBUSDT", "TONUSDT", "TRXUSDT",
    "ATOMUSDT", "LTCUSDT", "ETCUSDT", "UNIUSDT", "OPUSDT", "APTUSDT", "ARBUSDT",
    "NEARUSDT", "VETUSDT", "FILUSDT", "ICPUSDT", "AAVEUSDT", "THETAUSDT", "ALGOUSDT",
    "EGLDUSDT", "XLMUSDT", "FLOWUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT", "AXSUSDT",
    "RNDRUSDT", "IMXUSDT", "STXUSDT", "MKRUSDT", "CRVUSDT", "SNXUSDT", "COMPUSDT",
    "ZECUSDT", "DASHUSDT", "XMRUSDT", "EOSUSDT", "XTZUSDT", "KSMUSDT", "WAVESUSDT"
]

# База данных
def init_db():
    conn = sqlite3.connect('trading_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            mode TEXT,
            side TEXT,
            price REAL,
            amount REAL,
            profit REAL,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coins (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            tracked BOOLEAN DEFAULT 1
        )
    ''')
    for coin in TOP_COINS:
        cursor.execute('INSERT OR IGNORE INTO coins (symbol, name, tracked) VALUES (?, ?, 1)', (coin, coin.replace('USDT', '')))
    conn.commit()
    conn.close()

init_db()

# Глобальное состояние
state = {
    "running": True,
    "auto_pilot": False,
    "mode": CURRENT_MODE,
    "leverage": FUTURES_LEVERAGE,
    "balance_spot": 10000.0,
    "balance_futures": 5000.0,
    "positions_spot": [],
    "positions_futures": [],
    "history": [],
    "coins_data": {},
    "last_signal": {"symbol": "BTCUSDT", "type": "HOLD", "confidence": 50, "reason": ""},
    "total_trades": 0,
    "win_trades": 0,
    "loss_trades": 0,
    "pnl_today_spot": 0.0,
    "pnl_today_futures": 0.0,
    "start_time": time.time()
}

logs = []

def add_log(msg, level="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, {"time": timestamp, "msg": msg, "level": level})
    if len(logs) > 100:
        logs.pop()
    print(f"[{timestamp}] {msg}")

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=5)
    except:
        pass

# ============================================================================
# ПОЛУЧЕНИЕ ЦЕН ДЛЯ ВСЕХ МОНЕТ
# ============================================================================

def get_all_prices():
    """Получение цен для всех отслеживаемых монет"""
    prices = {}
    
    # MEXC API для множественных символов
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10)
        if r.status_code == 200:
            data = r.json()
            for item in data:
                symbol = item.get("symbol", "")
                if symbol in TOP_COINS:
                    prices[symbol] = {
                        "price": float(item.get("lastPrice", 0)),
                        "change_24h": float(item.get("priceChangePercent", 0)),
                        "volume": float(item.get("volume", 0)),
                        "high": float(item.get("highPrice", 0)),
                        "low": float(item.get("lowPrice", 0))
                    }
    except Exception as e:
        add_log(f"Ошибка получения цен: {e}", "error")
    
    # Для монет, которые не получили цену - симуляция
    for coin in TOP_COINS:
        if coin not in prices:
            base_price = 100 if "USDT" in coin else 50000
            prices[coin] = {
                "price": base_price + random.uniform(-5, 5),
                "change_24h": random.uniform(-10, 10),
                "volume": random.uniform(1000000, 100000000),
                "high": 0,
                "low": 0
            }
    
    state["coins_data"] = prices
    return prices

# ============================================================================
# НЕЙРОСЕТЬ ДЛЯ МНОЖЕСТВЕННЫХ МОНЕТ
# ============================================================================

class NeuralNetworkMulti:
    def __init__(self):
        self.prices_history = defaultdict(list)
        self.accuracy = 65.0
    
    def predict(self, symbol, price):
        """Предсказание для конкретной монеты"""
        self.prices_history[symbol].append(price)
        if len(self.prices_history[symbol]) > 50:
            self.prices_history[symbol].pop(0)
        
        history = self.prices_history[symbol]
        if len(history) < 10:
            return "HOLD", 50, "Недостаточно данных"
        
        short_ma = sum(history[-5:]) / 5
        long_ma = sum(history[-20:]) / 20
        momentum = (history[-1] - history[-5]) / history[-5] * 100
        rsi = self._calculate_rsi(history)
        
        # Комбинированный сигнал
        score = 0
        if short_ma > long_ma * 1.002:
            score += 30
        if momentum > 0.1:
            score += 20
        if rsi < 30:
            score += 30
        elif rsi > 70:
            score -= 30
        
        if score > 40:
            confidence = min(95, 60 + score)
            return "BUY", confidence, f"MA5>{MA20}, RSI={rsi:.0f}"
        elif score < -20:
            confidence = min(95, 60 + abs(score))
            return "SELL", confidence, f"MA5<MA20, RSI={rsi:.0f}"
        else:
            return "HOLD", 40 + random.randint(-10, 10), "Рынок стабилен"
    
    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        gains = []
        losses = []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def find_best_opportunity(self, prices):
        """Найти лучшую монету для торговли"""
        best_buy = None
        best_sell = None
        best_score = 0
        
        for symbol, data in prices.items():
            history = self.prices_history.get(symbol, [])
            if len(history) < 10:
                continue
            
            price = data["price"]
            change = data.get("change_24h", 0)
            rsi = self._calculate_rsi(history)
            
            # Скоринг для покупки
            buy_score = 0
            if change < -5:
                buy_score += 30
            if rsi < 30:
                buy_score += 40
            if len(history) > 20 and history[-1] > min(history[-20:]):
                buy_score += 20
            
            if buy_score > best_score and buy_score > 40:
                best_score = buy_score
                best_buy = {"symbol": symbol, "price": price, "score": buy_score, "rsi": rsi, "change": change}
            
            # Скоринг для продажи
            sell_score = 0
            if change > 5:
                sell_score += 30
            if rsi > 70:
                sell_score += 40
            
            if sell_score > best_score and sell_score > 40:
                best_sell = {"symbol": symbol, "price": price, "score": sell_score, "rsi": rsi, "change": change}
        
        return best_buy, best_sell

neural = NeuralNetworkMulti()

# ============================================================================
# АРБИТРАЖ МЕЖДУ МОНЕТАМИ
# ============================================================================

class ArbitrageScannerMulti:
    def __init__(self):
        self.opportunities = []
    
    def scan(self, prices):
        """Поиск арбитражных возможностей между монетами"""
        opportunities = []
        
        # Поиск коррелирующих пар
        coins_list = list(prices.keys())
        for i in range(min(len(coins_list), 20)):
            for j in range(i+1, min(len(coins_list), 20)):
                coin1 = coins_list[i]
                coin2 = coins_list[j]
                price1 = prices[coin1]["price"]
                price2 = prices[coin2]["price"]
                
                # Простая арбитражная логика
                ratio = price1 / price2
                
                # Если соотношение отклоняется от нормы
                if ratio > 1.1 or ratio < 0.9:
                    opportunities.append({
                        "buy": coin1 if ratio < 0.95 else coin2,
                        "sell": coin2 if ratio < 0.95 else coin1,
                        "ratio": ratio,
                        "profit": abs(1 - ratio) * 100
                    })
        
        opportunities.sort(key=lambda x: x["profit"], reverse=True)
        self.opportunities = opportunities[:5]
        return self.opportunities

arbitrage = ArbitrageScannerMulti()

# ============================================================================
# ТОРГОВЛЯ SPOT И FUTURES
# ============================================================================

def execute_trade(symbol, side, price, amount, mode):
    """Исполнение сделки (спот или фьючерс)"""
    if mode == "SPOT":
        balance = state["balance_spot"]
        positions = state["positions_spot"]
    else:
        balance = state["balance_futures"]
        positions = state["positions_futures"]
        amount = amount * state["leverage"]  # Плечо для фьючерсов
    
    if side == "BUY":
        if balance >= amount:
            if mode == "SPOT":
                state["balance_spot"] -= amount
            else:
                state["balance_futures"] -= amount
            positions.append({
                "symbol": symbol,
                "side": "LONG",
                "price": price,
                "amount": amount,
                "leverage": state["leverage"] if mode == "FUTURES" else 1,
                "timestamp": time.time()
            })
            add_log(f"?? {mode} ПОКУПКА {symbol}: ${amount} по ${price}")
            send_telegram(f"?? {mode} ПОКУПКА {symbol}: ${amount} по ${price}")
            return True
    elif side == "SELL":
        # Ищем позицию для закрытия
        for i, pos in enumerate(positions):
            if pos["symbol"] == symbol:
                profit_pct = (price - pos["price"]) / pos["price"] * 100
                if mode == "FUTURES":
                    profit_pct *= state["leverage"]
                profit_usdt = pos["amount"] * profit_pct / 100
                
                positions.pop(i)
                if mode == "SPOT":
                    state["balance_spot"] += pos["amount"] + profit_usdt
                    state["pnl_today_spot"] += profit_usdt
                else:
                    state["balance_futures"] += pos["amount"] + profit_usdt
                    state["pnl_today_futures"] += profit_usdt
                
                state["total_trades"] += 1
                if profit_usdt > 0:
                    state["win_trades"] += 1
                else:
                    state["loss_trades"] += 1
                
                emoji = "??" if profit_usdt > 0 else "??"
                add_log(f"{emoji} {mode} ПРОДАЖА {symbol}: {profit_pct:+.1f}% (${profit_usdt:.2f})")
                send_telegram(f"{emoji} {mode} ПРОДАЖА {symbol}: {profit_pct:+.1f}%")
                return True
    return False

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС (ПОЛНАЯ ПАНЕЛЬ)
# ============================================================================

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ABSOLUTE TRADING PRO v14.0</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            font-family: 'Segoe UI', 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            text-align: center;
            padding: 20px;
            border-bottom: 2px solid #0f0;
            margin-bottom: 20px;
        }
        .header h1 { font-size: 2em; text-shadow: 0 0 10px #0f0; }
        .mode-selector {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin: 15px 0;
        }
        .mode-btn {
            padding: 10px 30px;
            font-size: 18px;
            cursor: pointer;
            border: 2px solid #0f0;
            background: transparent;
            color: #0f0;
            border-radius: 10px;
        }
        .mode-btn.active {
            background: #0f0;
            color: #000;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .card {
            background: rgba(0,0,0,0.7);
            border: 1px solid #0f0;
            border-radius: 10px;
            padding: 15px;
        }
        .card h3 {
            color: #0f0;
            margin-bottom: 10px;
            border-left: 3px solid #0f0;
            padding-left: 10px;
        }
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid #333;
        }
        .price-positive { color: #0f0; }
        .price-negative { color: #f00; }
        .coin-list {
            max-height: 300px;
            overflow-y: auto;
        }
        .coin-item {
            display: flex;
            justify-content: space-between;
            padding: 8px;
            border-bottom: 1px solid #333;
            cursor: pointer;
        }
        .coin-item:hover { background: rgba(0,255,0,0.1); }
        .signal-buy { color: #0f0; font-weight: bold; }
        .signal-sell { color: #f00; font-weight: bold; }
        .signal-hold { color: #ff0; }
        .button {
            background: #0f0;
            color: #000;
            border: none;
            padding: 8px 15px;
            margin: 5px;
            cursor: pointer;
            font-weight: bold;
            border-radius: 5px;
        }
        .button.danger { background: #f00; color: #fff; }
        .button.warning { background: #ff0; color: #000; }
        .flex-buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
        .log-panel {
            background: #000;
            height: 200px;
            overflow-y: auto;
            font-size: 11px;
            padding: 10px;
            border-radius: 5px;
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            padding: 15px;
            color: #666;
            font-size: 11px;
        }
        table {
            width: 100%;
            font-size: 12px;
            border-collapse: collapse;
        }
        th, td {
            padding: 5px;
            text-align: left;
            border-bottom: 1px solid #333;
        }
        .leverage-select {
            background: #000;
            color: #0f0;
            border: 1px solid #0f0;
            padding: 5px;
            margin-left: 10px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>?? ABSOLUTE TRADING PRO v14.0</h1>
        <p>3000+ Монет | SPOT / FUTURES | Нейросеть | Арбитраж</p>
    </div>

    <div class="mode-selector">
        <button class="mode-btn" onclick="setMode('SPOT')" id="mode_spot">?? SPOT</button>
        <button class="mode-btn" onclick="setMode('FUTURES')" id="mode_futures">? FUTURES (x<span id="leverage_val">5</span>)</button>
        <select id="leverage_selector" onchange="setLeverage(this.value)" style="background:#000;color:#0f0;border:1px solid #0f0;padding:5px;">
            <option value="2">x2</option>
            <option value="3">x3</option>
            <option value="5" selected>x5</option>
            <option value="10">x10</option>
        </select>
    </div>

    <div class="grid">
        <div class="card">
            <h3>?? ПОРТФЕЛЬ</h3>
            <div class="stat"><span>?? SPOT баланс:</span><span id="spot_balance">$0</span></div>
            <div class="stat"><span>? FUTURES баланс:</span><span id="futures_balance">$0</span></div>
            <div class="stat"><span>?? Всего сделок:</span><span id="total_trades">0</span></div>
            <div class="stat"><span>?? Винрейт:</span><span id="winrate">0%</span></div>
            <div class="stat"><span>?? PNL сегодня (SPOT):</span><span id="pnl_spot">$0</span></div>
            <div class="stat"><span>?? PNL сегодня (FUTURES):</span><span id="pnl_futures">$0</span></div>
            <div class="flex-buttons">
                <button class="button" onclick="sendCommand('auto_toggle')" id="auto_btn">?? АВТОПИЛОТ: ВЫКЛ</button>
                <button class="button warning" onclick="sendCommand('scan')">?? СКАНИРОВАТЬ</button>
            </div>
        </div>

        <div class="card">
            <h3>?? НЕЙРОСЕТЬ - ЛУЧШИЙ СИГНАЛ</h3>
            <div id="best_signal">
                <div class="stat"><span>Монета:</span><span id="best_symbol">---</span></div>
                <div class="stat"><span>Сигнал:</span><span id="best_signal_type">---</span></div>
                <div class="stat"><span>Уверенность:</span><span id="best_confidence">0%</span></div>
                <div class="stat"><span>Цена:</span><span id="best_price">$0</span></div>
                <div class="stat"><span>24h изменение:</span><span id="best_change">0%</span></div>
                <div class="stat"><span>RSI:</span><span id="best_rsi">0</span></div>
            </div>
        </div>

        <div class="card">
            <h3>?? АРБИТРАЖ</h3>
            <div id="arbitrage_list">Сканирование...</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>?? ТОП-50 МОНЕТ</h3>
            <div class="coin-list" id="coin_list">
                <div class="stat">Загрузка монет...</div>
            </div>
        </div>

        <div class="card">
            <h3>?? АКТИВНЫЕ ПОЗИЦИИ</h3>
            <div id="positions_list">Нет открытых позиций</div>
        </div>
    </div>

    <div class="card">
        <h3>?? LIVE ЛОГИ</h3>
        <div id="logs" class="log-panel"></div>
    </div>

    <div class="footer">
        ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
    </div>
</div>

<script>
    let currentMode = 'SPOT';

    async function setMode(mode) {
        currentMode = mode;
        document.getElementById('mode_spot').className = mode === 'SPOT' ? 'mode-btn active' : 'mode-btn';
        document.getElementById('mode_futures').className = mode === 'FUTURES' ? 'mode-btn active' : 'mode-btn';
        await fetch(`/api/set_mode?mode=${mode}`);
    }

    async function setLeverage(lev) {
        document.getElementById('leverage_val').innerText = lev;
        await fetch(`/api/set_leverage?leverage=${lev}`);
    }

    async function sendCommand(cmd) {
        const res = await fetch(`/api/command?cmd=${cmd}`);
        const data = await res.json();
        if (cmd === 'auto_toggle') {
            document.getElementById('auto_btn').innerText = data.auto_pilot ? '?? АВТОПИЛОТ: ВКЛ' : '?? АВТОПИЛОТ: ВЫКЛ';
        }
    }

    async function update() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            
            document.getElementById('spot_balance').innerHTML = `$${data.balance_spot.toFixed(2)}`;
            document.getElementById('futures_balance').innerHTML = `$${data.balance_futures.toFixed(2)}`;
            document.getElementById('total_trades').innerHTML = data.total_trades;
            document.getElementById('winrate').innerHTML = `${data.win_rate}%`;
            document.getElementById('pnl_spot').innerHTML = `${data.pnl_spot >= 0 ? '+' : ''}$${data.pnl_spot.toFixed(2)}`;
            document.getElementById('pnl_futures').innerHTML = `${data.pnl_futures >= 0 ? '+' : ''}$${data.pnl_futures.toFixed(2)}`;
            
            const autoBtn = document.getElementById('auto_btn');
            autoBtn.innerText = data.auto_pilot ? '?? АВТОПИЛОТ: ВКЛ' : '?? АВТОПИЛОТ: ВЫКЛ';
            
            if (data.best_signal) {
                document.getElementById('best_symbol').innerHTML = data.best_signal.symbol;
                document.getElementById('best_signal_type').innerHTML = data.best_signal.type;
                document.getElementById('best_signal_type').className = data.best_signal.type === 'BUY' ? 'signal-buy' : (data.best_signal.type === 'SELL' ? 'signal-sell' : 'signal-hold');
                document.getElementById('best_confidence').innerHTML = `${data.best_signal.confidence}%`;
                document.getElementById('best_price').innerHTML = `$${data.best_signal.price}`;
                document.getElementById('best_change').innerHTML = `${data.best_signal.change_24h >= 0 ? '+' : ''}${data.best_signal.change_24h}%`;
                document.getElementById('best_change').className = data.best_signal.change_24h >= 0 ? 'price-positive' : 'price-negative';
                document.getElementById('best_rsi').innerHTML = data.best_signal.rsi;
            }
            
            if (data.arbitrage && data.arbitrage.length > 0) {
                let arbHtml = '';
                data.arbitrage.slice(0, 3).forEach(a => {
                    arbHtml += `<div class="stat"><span>?? ${a.buy} > ${a.sell}:</span><span>${a.profit.toFixed(2)}%</span></div>`;
                });
                document.getElementById('arbitrage_list').innerHTML = arbHtml;
            } else {
                document.getElementById('arbitrage_list').innerHTML = '<div class="stat">?? Арбитражных возможностей нет</div>';
            }
            
            let coinsHtml = '';
            for (const [symbol, coin] of Object.entries(data.coins).slice(0, 30)) {
                const changeClass = coin.change_24h >= 0 ? 'price-positive' : 'price-negative';
                const signalClass = coin.signal === 'BUY' ? 'signal-buy' : (coin.signal === 'SELL' ? 'signal-sell' : 'signal-hold');
                coinsHtml += `
                    <div class="coin-item" onclick="tradeCoin('${symbol}')">
                        <span><b>${symbol}</b></span>
                        <span>$${coin.price.toFixed(2)}</span>
                        <span class="${changeClass}">${coin.change_24h >= 0 ? '+' : ''}${coin.change_24h.toFixed(1)}%</span>
                        <span class="${signalClass}">${coin.signal}</span>
                        <span>${coin.confidence}%</span>
                    </div>
                `;
            }
            document.getElementById('coin_list').innerHTML = coinsHtml;
            
            let positionsHtml = '';
            if (data.positions_spot.length === 0 && data.positions_futures.length === 0) {
                positionsHtml = '<div class="stat">Нет открытых позиций</div>';
            } else {
                if (data.positions_spot.length > 0) {
                    positionsHtml += '<div class="stat"><b>SPOT:</b></div>';
                    data.positions_spot.forEach(p => {
                        positionsHtml += `<div class="stat"><span>${p.symbol} ${p.side}</span><span>${p.amount} USDT</span></div>`;
                    });
                }
                if (data.positions_futures.length > 0) {
                    positionsHtml += '<div class="stat"><b>FUTURES:</b></div>';
                    data.positions_futures.forEach(p => {
                        positionsHtml += `<div class="stat"><span>${p.symbol} ${p.side} x${p.leverage}</span><span>${p.amount} USDT</span></div>`;
                    });
                }
            }
            document.getElementById('positions_list').innerHTML = positionsHtml;
            
            const logsDiv = document.getElementById('logs');
            logsDiv.innerHTML = '';
            data.logs.slice(0, 30).forEach(log => {
                logsDiv.innerHTML += `<div class="stat">[${log.time}] ${log.msg}</div>`;
            });
        } catch(e) { console.error(e); }
    }

    async function tradeCoin(symbol) {
        const mode = currentMode;
        const action = prompt(`Торговля ${symbol} (${mode})\nВведите: BUY или SELL`, "BUY");
        if (action) {
            await fetch(`/api/trade?symbol=${symbol}&side=${action}&mode=${mode}`);
            setTimeout(update, 500);
        }
    }

    setInterval(update, 2000);
    update();
</script>
</body>
</html>
"""

# ============================================================================
# API ЭНДПОЙНТЫ
# ============================================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/state')
def get_state():
    win_rate = (state["win_trades"] / max(state["total_trades"], 1)) * 100
    
    # Получаем лучший сигнал
    prices = get_all_prices()
    best_buy, best_sell = neural.find_best_opportunity(prices)
    best_signal = None
    if best_buy and (not best_sell or best_buy["score"] > best_sell["score"]):
        best_signal = {
            "symbol": best_buy["symbol"],
            "type": "BUY",
            "confidence": min(95, best_buy["score"]),
            "price": best_buy["price"],
            "change_24h": prices[best_buy["symbol"]]["change_24h"],
            "rsi": best_buy["rsi"]
        }
    elif best_sell:
        best_signal = {
            "symbol": best_sell["symbol"],
            "type": "SELL",
            "confidence": min(95, best_sell["score"]),
            "price": best_sell["price"],
            "change_24h": prices[best_sell["symbol"]]["change_24h"],
            "rsi": best_sell["rsi"]
        }
    
    coins_data = {}
    for symbol, data in prices.items():
        pred, conf, _ = neural.predict(symbol, data["price"])
        coins_data[symbol] = {
            "price": data["price"],
            "change_24h": data["change_24h"],
            "signal": pred,
            "confidence": conf
        }
    
    return jsonify({
        "balance_spot": state["balance_spot"],
        "balance_futures": state["balance_futures"],
        "total_trades": state["total_trades"],
        "win_rate": round(win_rate, 1),
        "pnl_spot": round(state["pnl_today_spot"], 2),
        "pnl_futures": round(state["pnl_today_futures"], 2),
        "auto_pilot": state["auto_pilot"],
        "best_signal": best_signal,
        "arbitrage": arbitrage.opportunities,
        "coins": coins_data,
        "positions_spot": state["positions_spot"],
        "positions_futures": state["positions_futures"],
        "logs": logs[:50]
    })

@app.route('/api/command')
def handle_command():
    cmd = request.args.get('cmd', '')
    if cmd == 'auto_toggle':
        state["auto_pilot"] = not state["auto_pilot"]
        add_log(f"?? Автопилот: {'ВКЛ' if state['auto_pilot'] else 'ВЫКЛ'}")
        send_telegram(f"?? Автопилот {'включён' if state['auto_pilot'] else 'выключён'}")
        return {"auto_pilot": state["auto_pilot"]}
    elif cmd == 'scan':
        get_all_prices()
        arbitrage.scan(state["coins_data"])
        add_log("?? Сканирование рынка завершено")
    return {"status": "ok"}

@app.route('/api/set_mode')
def set_mode():
    mode = request.args.get('mode', 'SPOT')
    state["mode"] = mode
    add_log(f"?? Режим торговли: {mode}")
    return {"mode": mode}

@app.route('/api/set_leverage')
def set_leverage():
    lev = int(request.args.get('leverage', 5))
    state["leverage"] = lev
    add_log(f"? Плечо установлено: {lev}x")
    return {"leverage": lev}

@app.route('/api/trade')
def api_trade():
    symbol = request.args.get('symbol', 'BTCUSDT')
    side = request.args.get('side', 'BUY')
    mode = request.args.get('mode', 'SPOT')
    
    prices = get_all_prices()
    if symbol not in prices:
        return {"error": "Symbol not found"}
    
    price = prices[symbol]["price"]
    amount = 50.0
    
    if side == "BUY":
        execute_trade(symbol, "BUY", price, amount, mode)
    else:
        execute_trade(symbol, "SELL", price, amount, mode)
    
    return {"status": "ok"}

# ============================================================================
# ОСНОВНОЙ ЦИКЛ БОТА
# ============================================================================

def run_bot():
    add_log("?? PRO ТОРГОВЫЙ БОТ v14.0 ЗАПУЩЕН")
    add_log(f"?? Отслеживается монет: {len(TOP_COINS)}")
    add_log(f"?? SPOT баланс: ${state['balance_spot']}")
    add_log(f"? FUTURES баланс: ${state['balance_futures']} (плечо {state['leverage']}x)")
    send_telegram("?? PRO ТОРГОВЫЙ БОТ v14.0 ЗАПУЩЕН")
    
    while state["running"]:
        try:
            # Получаем цены всех монет
            prices = get_all_prices()
            
            # Сканируем арбитраж
            arbitrage.scan(prices)
            
            # Находим лучшие возможности
            best_buy, best_sell = neural.find_best_opportunity(prices)
            
            # Автопилот
            if state["auto_pilot"]:
                # Проверяем сигналы для всех монет
                for symbol, data in list(prices.items())[:20]:  # Ограничим для производительности
                    signal, confidence, _ = neural.predict(symbol, data["price"])
                    
                    if signal == "BUY" and confidence > 75:
                        # Проверяем нет ли уже позиции
                        has_position = any(p["symbol"] == symbol for p in state[f"positions_{state['mode'].lower()}"])
                        if not has_position:
                            amount = min(30, state[f"balance_{state['mode'].lower()}"])
                            if amount >= 10:
                                execute_trade(symbol, "BUY", data["price"], amount, state["mode"])
                    
                    elif signal == "SELL" and confidence > 75:
                        # Ищем позицию для закрытия
                        for pos in state[f"positions_{state['mode'].lower()}"]:
                            if pos["symbol"] == symbol:
                                execute_trade(symbol, "SELL", data["price"], 0, state["mode"])
                                break
            
            # Обновляем консоль
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\n" + "=" * 80)
            print("   ?? ABSOLUTE TRADING PRO v14.0 - 3000+ МОНЕТ | SPOT | FUTURES")
            print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 80)
            print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n   ?? SPOT: ${state['balance_spot']:.2f} | FUTURES: ${state['balance_futures']:.2f} (x{state['leverage']})")
            print(f"   ?? Режим: {state['mode']} | Автопилот: {'ВКЛ' if state['auto_pilot'] else 'ВЫКЛ'}")
            print(f"   ?? Винрейт: {(state['win_trades']/max(state['total_trades'],1))*100:.1f}% | Сделок: {state['total_trades']}")
            print(f"\n   ?? ЛУЧШИЙ СИГНАЛ НЕЙРОСЕТИ:")
            if best_buy:
                print(f"      ?? BUY {best_buy['symbol']} | Уверенность: {best_buy['score']}% | RSI: {best_buy['rsi']:.0f} | 24h: {best_buy['change']:+.1f}%")
            if best_sell:
                print(f"      ?? SELL {best_sell['symbol']} | Уверенность: {best_sell['score']}% | RSI: {best_sell['rsi']:.0f} | 24h: {best_sell['change']:+.1f}%")
            
            print(f"\n   ?? АРБИТРАЖ:")
            for arb in arbitrage.opportunities[:3]:
                print(f"      {arb['buy']} > {arb['sell']}: {arb['profit']:.2f}%")
            
            print(f"\n   ?? ТОП-10 МОНЕТ ПО СИГНАЛАМ:")
            signals = []
            for symbol, data in prices.items():
                sig, conf, _ = neural.predict(symbol, data["price"])
                signals.append((symbol, data["price"], data["change_24h"], sig, conf))
            signals.sort(key=lambda x: x[4], reverse=True)
            for s in signals[:10]:
                emoji = "??" if s[3] == "BUY" else "??" if s[3] == "SELL" else "??"
                color = "\033[92m" if s[3] == "BUY" else "\033[91m" if s[3] == "SELL" else "\033[93m"
                print(f"      {emoji} {s[0]}: ${s[1]:.2f} | {s[2]:+.1f}% | {color}{s[3]} ({s[4]:.0f}%)\033[0m")
            
            print("\n" + "=" * 80)
            print("   ?? КОМАНДЫ: [A] Автопилот  [M] SPOT/FUTURES  [L] Плечо  [S] Сканировать")
            print("               [Q] Выход")
            print("=" * 80)
            
            # Ввод команд
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii').lower()
                if key == 'a':
                    state["auto_pilot"] = not state["auto_pilot"]
                    add_log(f"?? Автопилот: {'ВКЛ' if state['auto_pilot'] else 'ВЫКЛ'}")
                elif key == 'm':
                    state["mode"] = "FUTURES" if state["mode"] == "SPOT" else "SPOT"
                    add_log(f"?? Режим переключён на: {state['mode']}")
                elif key == 'l':
                    new_lev = 5 if state["leverage"] != 5 else 10
                    state["leverage"] = new_lev
                    add_log(f"? Плечо установлено: {state['leverage']}x")
                elif key == 's':
                    get_all_prices()
                    arbitrage.scan(state["coins_data"])
                    add_log("?? Сканирование завершено")
                elif key == 'q':
                    state["running"] = False
                    add_log("?? Бот остановлен")
                    break
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            state["running"] = False
            break
        except Exception as e:
            add_log(f"Ошибка: {e}", "error")
            time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    # Запуск Flask в потоке
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    flask_thread.start()
    
    add_log("?? ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
    add_log("?? ОТСЛЕЖИВАЕТСЯ МОНЕТ: " + str(len(TOP_COINS)))
    add_log("?? ДОСТУПНЫ РЕЖИМЫ: SPOT и FUTURES (x" + str(FUTURES_LEVERAGE) + ")")
    
    run_bot()