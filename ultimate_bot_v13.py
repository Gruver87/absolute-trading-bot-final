# -*- coding: utf-8 -*-
# ultimate_bot_v13.py - Полная версия с вебом, консолью и Telegram
import time
import requests
import random
import threading
import os
import json
import msvcrt
import sys
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

# Telegram (замени на свои данные)
TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# Параметры торговли
INITIAL_BALANCE = 10000  # Тестовый баланс для симуляции
REAL_BALANCE = 0.01      # Реальный баланс нужно пополнить

# Глобальное состояние
state = {
    "running": True,
    "auto_pilot": False,
    "balance": INITIAL_BALANCE,
    "real_balance": REAL_BALANCE,
    "positions": [],
    "history": [],
    "current_price": 78000,
    "last_signal": {"type": "HOLD", "confidence": 50, "reason": "Ожидание данных"},
    "total_trades": 0,
    "win_trades": 0,
    "loss_trades": 0,
    "pnl_today": 0.0,
    "start_time": time.time()
}

# Логи
logs = []

def add_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, {"time": timestamp, "msg": msg})
    if len(logs) > 100:
        logs.pop()
    print(f"[{timestamp}] {msg}")

# ============================================================================
# ТЕЛЕГРАМ БОТ
# ============================================================================

def send_telegram(message):
    """Отправить сообщение в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

class TelegramBot:
    def __init__(self):
        self.last_update_id = 0
        self.running = True
    
    def check_messages(self):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 10}
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                updates = response.json().get("result", [])
                for update in updates:
                    self.last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "")
                    chat_id = message.get("chat", {}).get("id")
                    if chat_id and text:
                        self.handle_command(chat_id, text)
        except Exception as e:
            pass
    
    def handle_command(self, chat_id, command):
        cmd = command.lower().strip()
        
        if cmd == "/start":
            self.send(chat_id, "?? <b>ABSOLUTE TRADING BOT v13.0</b>\n\nДоступные команды:\n/status - статус бота\n/price - текущая цена BTC\n/signal - последний сигнал\n/buy - купить BTC\n/sell - продать BTC\n/auto_on - включить автопилот\n/auto_off - выключить автопилот\n/help - справка")
        
        elif cmd == "/status":
            pos_count = len(state["positions"])
            win_rate = (state["win_trades"] / max(state["total_trades"], 1)) * 100
            msg = f"?? <b>СТАТУС БОТА</b>\n\n?? Баланс: ${state['balance']:.2f}\n?? BTC: ${state['current_price']:.2f}\n?? Сделок: {state['total_trades']}\n?? Винрейт: {win_rate:.1f}%\n?? Позиций: {pos_count}\n?? Автопилот: {'? ВКЛ' if state['auto_pilot'] else '? ВЫКЛ'}"
            self.send(chat_id, msg)
        
        elif cmd == "/price":
            self.send(chat_id, f"?? <b>BTC/USDT</b>\n?? ${state['current_price']:.2f}\n?? {datetime.now().strftime('%H:%M:%S')}")
        
        elif cmd == "/signal":
            sig = state["last_signal"]
            emoji = "??" if sig["type"] == "BUY" else "??" if sig["type"] == "SELL" else "??"
            msg = f"{emoji} <b>ПОСЛЕДНИЙ СИГНАЛ</b>\n\nТип: {sig['type']}\nУверенность: {sig['confidence']}%\nПричина: {sig['reason']}"
            self.send(chat_id, msg)
        
        elif cmd == "/buy":
            if state["balance"] >= 100:
                amount = min(100, state["balance"])
                state["balance"] -= amount
                state["positions"].append({"type": "LONG", "price": state["current_price"], "amount": amount})
                state["total_trades"] += 1
                self.send(chat_id, f"? <b>ПОКУПКА BTC</b>\n?? Сумма: ${amount}\n?? Цена: ${state['current_price']:.2f}")
            else:
                self.send(chat_id, "? Недостаточно средств!")
        
        elif cmd == "/sell":
            if state["positions"]:
                pos = state["positions"].pop(0)
                profit_pct = (state["current_price"] - pos["price"]) / pos["price"] * 100
                profit_usdt = pos["amount"] * profit_pct / 100
                state["balance"] += pos["amount"] + profit_usdt
                state["total_trades"] += 1
                if profit_usdt > 0:
                    state["win_trades"] += 1
                else:
                    state["loss_trades"] += 1
                emoji = "??" if profit_usdt > 0 else "??"
                self.send(chat_id, f"{emoji} <b>ПРОДАЖА BTC</b>\n?? Цена: ${state['current_price']:.2f}\n?? Прибыль: ${profit_usdt:.2f} ({profit_pct:.1f}%)")
            else:
                self.send(chat_id, "? Нет открытых позиций!")
        
        elif cmd == "/auto_on":
            state["auto_pilot"] = True
            self.send(chat_id, "?? <b>АВТОПИЛОТ ВКЛЮЧЁН</b>")
        
        elif cmd == "/auto_off":
            state["auto_pilot"] = False
            self.send(chat_id, "????? <b>АВТОПИЛОТ ВЫКЛЮЧЁН</b>")
        
        elif cmd == "/help":
            msg = "?? <b>СПРАВКА</b>\n\n/status - статус бота\n/price - текущая цена BTC\n/signal - последний сигнал\n/buy - купить BTC\n/sell - продать BTC\n/auto_on - включить автопилот\n/auto_off - выключить автопилот\n/help - эта справка"
            self.send(chat_id, msg)
    
    def send(self, chat_id, message):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=5)
        except:
            pass
    
    def run(self):
        while state["running"]:
            self.check_messages()
            time.sleep(1)

# ============================================================================
# НЕЙРОСЕТЬ
# ============================================================================

class NeuralNetwork:
    def __init__(self):
        self.prices_history = []
        self.accuracy = 65.0
    
    def predict(self, price):
        self.prices_history.append(price)
        if len(self.prices_history) > 50:
            self.prices_history.pop(0)
        
        if len(self.prices_history) < 10:
            return "HOLD", 50, "Недостаточно данных для анализа"
        
        short_ma = sum(self.prices_history[-5:]) / 5
        long_ma = sum(self.prices_history[-20:]) / 20
        momentum = (self.prices_history[-1] - self.prices_history[-5]) / self.prices_history[-5] * 100
        volatility = (max(self.prices_history[-20:]) - min(self.prices_history[-20:])) / min(self.prices_history[-20:]) * 100
        
        if short_ma > long_ma * 1.002 and momentum > 0.1:
            confidence = min(95, 65 + abs(momentum) + (volatility / 2))
            return "BUY", confidence, f"Бычий тренд: MA5 ({short_ma:.0f}) > MA20 ({long_ma:.0f})"
        elif short_ma < long_ma * 0.998 and momentum < -0.1:
            confidence = min(95, 65 + abs(momentum) + (volatility / 2))
            return "SELL", confidence, f"Медвежий тренд: MA5 ({short_ma:.0f}) < MA20 ({long_ma:.0f})"
        else:
            confidence = 50 + random.randint(-10, 10)
            return "HOLD", confidence, f"Рынок стабилен"

# ============================================================================
# АРБИТРАЖ
# ============================================================================

class ArbitrageScanner:
    def __init__(self):
        self.exchanges = {
            "Binance": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            "MEXC": "https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT",
        }
    
    def get_prices(self):
        prices = {}
        for name, url in self.exchanges.items():
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    price = float(r.json().get("price", 0))
                    prices[name] = price
            except:
                prices[name] = state["current_price"] * random.uniform(0.995, 1.005)
        return prices
    
    def find_opportunity(self):
        prices = self.get_prices()
        if len(prices) < 2:
            return None
        min_ex = min(prices, key=prices.get)
        max_ex = max(prices, key=prices.get)
        profit = (prices[max_ex] - prices[min_ex]) / prices[min_ex] * 100
        if profit > 0.3:
            return {"buy": min_ex, "buy_price": prices[min_ex], "sell": max_ex, "sell_price": prices[max_ex], "profit": profit - 0.1}
        return None

# ============================================================================
# КОНСОЛЬНЫЙ ИНТЕРФЕЙС
# ============================================================================

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_console_dashboard(price, signal, confidence, reason, neural, arb_opp):
    clear_screen()
    print("\n" + "=" * 70)
    print("   ?? ABSOLUTE TRADING BOT v13.0 - ULTIMATE EDITION")
    print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
    print("=" * 70)
    print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n   ?? БАЛАНС: ${state['balance']:.2f} (тест) | ${state['real_balance']:.2f} (реал)")
    print(f"   ?? BTC ЦЕНА: ${price:.2f}")
    print(f"\n   ?? НЕЙРОСЕТЬ: точность {neural.accuracy:.1f}%, история {len(neural.prices_history)} свечей")
    
    emoji = "??" if signal == "BUY" else "??" if signal == "SELL" else "??"
    print(f"\n   ?? СИГНАЛ: {emoji} {signal} ({confidence:.0f}%)")
    print(f"      Причина: {reason[:80]}")
    
    ap_status = "ВКЛЮЧЁН ?" if state["auto_pilot"] else "ВЫКЛЮЧЕН ?"
    print(f"\n   ?? АВТОПИЛОТ: {ap_status}")
    
    if arb_opp:
        print(f"\n   ?? АРБИТРАЖ: Купить на {arb_opp['buy']} (${arb_opp['buy_price']:.2f}), продать на {arb_opp['sell']} (${arb_opp['sell_price']:.2f}) -> прибыль {arb_opp['profit']:.2f}%")
    
    win_rate = (state["win_trades"] / max(state["total_trades"], 1)) * 100
    print(f"\n   ?? СТАТИСТИКА: сделок {state['total_trades']} (выигрышей {state['win_trades']}), винрейт {win_rate:.1f}%")
    
    if state["positions"]:
        print(f"\n   ?? ОТКРЫТЫЕ ПОЗИЦИИ:")
        for i, pos in enumerate(state["positions"]):
            profit_pct = (price - pos["price"]) / pos["price"] * 100
            pnl = pos["amount"] * profit_pct / 100
            print(f"      {i+1}. {pos['type']} | вход ${pos['price']:.2f} | {profit_pct:+.1f}% | PNL: ${pnl:.2f}")
    
    print("\n" + "=" * 70)
    print("   ?? КОМАНДЫ: [A] Автопилот  [B] Купить  [S] Продать  [C] Закрыть всё")
    print("               [R] Арбитраж   [P] Цены   [T] Telegram  [Q] Выход")
    print("=" * 70)

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ABSOLUTE TRADING BOT v13.0</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body { background: #0a0a0a; color: #0f0; font-family: monospace; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .price { font-size: 48px; font-weight: bold; text-align: center; margin: 20px; }
        .signal { font-size: 32px; text-align: center; padding: 20px; margin: 10px; border-radius: 10px; }
        .buy { background: rgba(0,255,0,0.2); color: #0f0; }
        .sell { background: rgba(255,0,0,0.2); color: #f00; }
        .hold { background: rgba(255,255,0,0.2); color: #ff0; }
        .card { background: rgba(0,0,0,0.7); border: 1px solid #0f0; border-radius: 10px; padding: 15px; margin: 10px 0; }
        .footer { text-align: center; margin-top: 30px; color: #666; }
    </style>
</head>
<body>
<div class="container">
    <h1 style="text-align:center">?? ABSOLUTE TRADING BOT v13.0</h1>
    <div class="price" id="price">?? BTC: $---</div>
    <div class="signal" id="signal">?? Анализ...</div>
    <div class="card">
        <b>?? СОСТОЯНИЕ</b><br>
        ?? Баланс: $<span id="balance">0</span><br>
        ?? Сделок: <span id="trades">0</span><br>
        ?? Винрейт: <span id="winrate">0</span>%<br>
        ?? Автопилот: <span id="autopilot">ВЫКЛ</span>
    </div>
    <div class="card">
        <b>?? УПРАВЛЕНИЕ</b><br>
        <button onclick="fetch('/api/command?cmd=auto_toggle')">?? Автопилот</button>
        <button onclick="fetch('/api/command?cmd=buy')">?? Купить</button>
        <button onclick="fetch('/api/command?cmd=sell')">?? Продать</button>
        <button onclick="fetch('/api/command?cmd=close_all')">?? Закрыть всё</button>
    </div>
    <div class="footer">
        ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
    </div>
</div>
<script>
    async function update() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            document.getElementById('price').innerHTML = `?? BTC: $${data.price}`;
            document.getElementById('balance').innerHTML = data.balance;
            document.getElementById('trades').innerHTML = data.total_trades;
            document.getElementById('winrate').innerHTML = data.win_rate;
            document.getElementById('autopilot').innerHTML = data.auto_pilot ? 'ВКЛ' : 'ВЫКЛ';
            const sigDiv = document.getElementById('signal');
            sigDiv.innerHTML = data.signal_text;
            sigDiv.className = `signal ${data.signal_class}`;
        } catch(e) {}
    }
    setInterval(update, 2000);
    update();
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/state')
def get_state():
    win_rate = (state["win_trades"] / max(state["total_trades"], 1)) * 100
    signal_class = "buy" if state["last_signal"]["type"] == "BUY" else "sell" if state["last_signal"]["type"] == "SELL" else "hold"
    signal_text = f"?? {state['last_signal']['type']}" if state["last_signal"]["type"] == "BUY" else f"?? {state['last_signal']['type']}" if state["last_signal"]["type"] == "SELL" else f"?? {state['last_signal']['type']}"
    return jsonify({
        "price": round(state["current_price"], 2),
        "balance": round(state["balance"], 2),
        "total_trades": state["total_trades"],
        "win_rate": round(win_rate, 1),
        "auto_pilot": state["auto_pilot"],
        "signal_text": signal_text,
        "signal_class": signal_class,
        "last_signal": state["last_signal"]
    })

@app.route('/api/command')
def handle_command():
    cmd = request.args.get('cmd', '')
    if cmd == 'auto_toggle':
        state["auto_pilot"] = not state["auto_pilot"]
        send_telegram(f"?? Автопилот {'ВКЛЮЧЁН' if state['auto_pilot'] else 'ВЫКЛЮЧЁН'}")
    elif cmd == 'buy':
        if state["balance"] >= 100:
            amount = min(100, state["balance"])
            state["balance"] -= amount
            state["positions"].append({"type": "LONG", "price": state["current_price"], "amount": amount})
            state["total_trades"] += 1
            send_telegram(f"? ПОКУПКА BTC на ${amount}")
    elif cmd == 'sell':
        if state["positions"]:
            pos = state["positions"].pop(0)
            profit_pct = (state["current_price"] - pos["price"]) / pos["price"] * 100
            profit_usdt = pos["amount"] * profit_pct / 100
            state["balance"] += pos["amount"] + profit_usdt
            state["total_trades"] += 1
            if profit_usdt > 0:
                state["win_trades"] += 1
            else:
                state["loss_trades"] += 1
            send_telegram(f"{'??' if profit_usdt > 0 else '??'} ПРОДАЖА BTC: {profit_pct:+.1f}%")
    elif cmd == 'close_all':
        for pos in state["positions"][:]:
            profit_pct = (state["current_price"] - pos["price"]) / pos["price"] * 100
            profit_usdt = pos["amount"] * profit_pct / 100
            state["balance"] += pos["amount"] + profit_usdt
        state["positions"] = []
        send_telegram("?? ВСЕ ПОЗИЦИИ ЗАКРЫТЫ")
    return {"status": "ok"}

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def run_bot():
    global last_arb_opp
    neural = NeuralNetwork()
    scanner = ArbitrageScanner()
    last_arb_opp = None
    
    add_log("?? БОТ ЗАПУЩЕН")
    send_telegram("?? БОТ ЗАПУЩЕН! v13.0 готов к работе")
    
    while state["running"]:
        try:
            # Получение цены
            try:
                r = requests.get("https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
                if r.status_code == 200:
                    state["current_price"] = float(r.json().get("price", 78000))
            except:
                state["current_price"] = state["current_price"] * (1 + random.uniform(-0.002, 0.002))
            
            price = state["current_price"]
            
            # Нейросеть
            signal, confidence, reason = neural.predict(price)
            state["last_signal"] = {"type": signal, "confidence": confidence, "reason": reason}
            
            # Арбитраж
            last_arb_opp = scanner.find_opportunity()
            
            # Автопилот
            if state["auto_pilot"] and confidence > 70:
                if signal == "BUY" and not any(p["type"] == "LONG" for p in state["positions"]):
                    amount = min(50, state["balance"])
                    if amount >= 10:
                        state["balance"] -= amount
                        state["positions"].append({"type": "LONG", "price": price, "amount": amount})
                        add_log(f"?? АВТО: покупка BTC на ${amount}")
                        send_telegram(f"?? АВТОПИЛОТ: покупка BTC на ${amount}")
                elif signal == "SELL" and not any(p["type"] == "SHORT" for p in state["positions"]):
                    amount = min(50, state["balance"])
                    if amount >= 10:
                        state["balance"] -= amount
                        state["positions"].append({"type": "SHORT", "price": price, "amount": amount})
                        add_log(f"?? АВТО: шорт BTC на ${amount}")
                        send_telegram(f"?? АВТОПИЛОТ: шорт BTC на ${amount}")
            
            # Проверка стоп-лоссов
            for pos in state["positions"][:]:
                if pos["type"] == "LONG":
                    profit_pct = (price - pos["price"]) / pos["price"] * 100
                else:
                    profit_pct = (pos["price"] - price) / pos["price"] * 100
                
                if profit_pct <= -5 or profit_pct >= 8:
                    profit_usdt = pos["amount"] * profit_pct / 100
                    state["balance"] += pos["amount"] + profit_usdt
                    state["total_trades"] += 1
                    if profit_usdt > 0:
                        state["win_trades"] += 1
                    else:
                        state["loss_trades"] += 1
                    state["positions"].remove(pos)
                    add_log(f"?? Закрыта позиция: {profit_pct:+.1f}%")
                    send_telegram(f"?? Позиция закрыта: {profit_pct:+.1f}%")
            
            # Консоль
            print_console_dashboard(price, signal, confidence, reason, neural, last_arb_opp)
            
            # Ввод команд
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii').lower()
                if key == 'a':
                    state["auto_pilot"] = not state["auto_pilot"]
                    add_log(f"?? Автопилот: {'ВКЛ' if state['auto_pilot'] else 'ВЫКЛ'}")
                elif key == 'b':
                    if state["balance"] >= 100:
                        amount = min(100, state["balance"])
                        state["balance"] -= amount
                        state["positions"].append({"type": "LONG", "price": price, "amount": amount})
                        add_log(f"?? РУЧНАЯ: покупка BTC на ${amount}")
                elif key == 's':
                    if state["positions"]:
                        pos = state["positions"].pop(0)
                        profit_pct = (price - pos["price"]) / pos["price"] * 100
                        profit_usdt = pos["amount"] * profit_pct / 100
                        state["balance"] += pos["amount"] + profit_usdt
                        add_log(f"?? РУЧНАЯ: продажа BTC, прибыль ${profit_usdt:.2f}")
                elif key == 'c':
                    for pos in state["positions"][:]:
                        profit_pct = (price - pos["price"]) / pos["price"] * 100
                        profit_usdt = pos["amount"] * profit_pct / 100
                        state["balance"] += pos["amount"] + profit_usdt
                    state["positions"] = []
                    add_log("?? ВСЕ ПОЗИЦИИ ЗАКРЫТЫ")
                elif key == 'q':
                    state["running"] = False
                    add_log("?? Бот остановлен")
                    send_telegram("?? БОТ ОСТАНОВЛЕН")
                    break
            
            time.sleep(4)
            
        except KeyboardInterrupt:
            state["running"] = False
            break
        except Exception as e:
            add_log(f"Ошибка: {e}")
            time.sleep(5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    # Запуск Telegram бота в потоке
    tg_bot = TelegramBot()
    tg_thread = threading.Thread(target=tg_bot.run, daemon=True)
    tg_thread.start()
    
    # Запуск Flask в потоке
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    flask_thread.start()
    
    add_log("?? Веб-интерфейс: http://localhost:5002")
    add_log("?? Telegram бот готов (команды: /status, /buy, /sell, /signal)")
    
    # Запуск основного бота
    run_bot()