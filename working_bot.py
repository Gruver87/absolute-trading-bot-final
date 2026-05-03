# -*- coding: utf-8 -*-
# working_bot.py - РАБОЧАЯ ВЕРСИЯ БОТА
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import random
import threading
import os
import msvcrt
from datetime import datetime
from flask import Flask, jsonify, render_template_string

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# Режим работы: "TEST" - симуляция, "REAL" - реальные данные
MODE = "TEST"

# Монеты для торговли
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class TradingBot:
    def __init__(self):
        self.balance = 10000
        self.active_trades = []
        self.trade_history = []
        self.auto_pilot = True
        self.logs = []
        self.mode = MODE
        self.session_start = datetime.now()
        
        self.add_log(f"?? БОТ ЗАПУЩЕН | Режим: {self.mode} | Баланс: ${self.balance}")
        self.send_telegram(f"?? БОТ ЗАПУЩЕН! Режим: {self.mode}")
    
    def add_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.insert(0, {"time": timestamp, "msg": msg})
        if len(self.logs) > 100:
            self.logs.pop()
        print(f"[{timestamp}] {msg}")
    
    def send_telegram(self, msg):
        try:
            import requests
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:400]}, timeout=3)
        except Exception as e:
            pass
    
    def get_price(self, symbol):
        if self.mode == "TEST":
            # Симуляция цен
            if symbol == "BTCUSDT":
                base = 78000
            elif symbol == "ETHUSDT":
                base = 3500
            elif symbol == "SOLUSDT":
                base = 150
            elif symbol == "BNBUSDT":
                base = 600
            else:
                base = 100
            return base + random.uniform(-base*0.02, base*0.02)
        
        # Реальный режим (MEXC API)
        try:
            import requests
            r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                return float(r.json().get("price", 0))
        except:
            pass
        return 0
    
    def analyze(self, symbol, price):
        """Анализ рынка и генерация сигналов"""
        if self.mode == "TEST":
            # Симуляция сигналов нейросети
            rnd = random.random()
            if rnd < 0.25:
                confidence = random.randint(65, 95)
                return "BUY", confidence, ["Положительный моментум", "Объём выше среднего"]
            elif rnd < 0.5:
                confidence = random.randint(65, 95)
                return "SELL", confidence, ["Отрицательный моментум", "Сопротивление достигнуто"]
            else:
                return "HOLD", random.randint(40, 60), ["Рынок стабилен"]
        
        # Реальный анализ (упрощённый)
        return "HOLD", 50, ["Нет данных"]
    
    def execute_trade(self, symbol, side, price, confidence, reasons):
        """Исполнение сделки"""
        if not self.auto_pilot:
            return None
        
        amount = min(50, self.balance * 0.1)
        if amount < 10:
            return None
        
        if side == "BUY":
            stop_loss = price * 0.98
            take_profit = price * 1.04
        else:
            stop_loss = price * 1.02
            take_profit = price * 0.96
        
        trade = {
            "id": len(self.trade_history) + len(self.active_trades) + 1,
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "amount": amount,
            "confidence": confidence,
            "reasons": reasons,
            "entry_time": time.time(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "open"
        }
        
        self.active_trades.append(trade)
        self.balance -= amount
        
        msg = f"? {side} {symbol}: ${amount:.0f} по ${price:.0f} (уверенность {confidence:.0f}%)"
        self.add_log(msg)
        self.send_telegram(msg)
        
        return trade
    
    def update_trades(self):
        """Обновление открытых сделок"""
        closed = []
        
        for trade in self.active_trades[:]:
            price = self.get_price(trade["symbol"])
            if price == 0:
                continue
            
            if trade["side"] == "BUY":
                profit_pct = (price - trade["entry_price"]) / trade["entry_price"] * 100
                
                if price <= trade["stop_loss"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "stop_loss"
                    closed.append(trade)
                    self.active_trades.remove(trade)
                
                elif price >= trade["take_profit"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "take_profit"
                    closed.append(trade)
                    self.active_trades.remove(trade)
            
            else:  # SELL
                profit_pct = (trade["entry_price"] - price) / trade["entry_price"] * 100
                
                if price >= trade["stop_loss"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "stop_loss"
                    closed.append(trade)
                    self.active_trades.remove(trade)
                
                elif price <= trade["take_profit"]:
                    trade["exit_price"] = price
                    trade["profit_pct"] = profit_pct
                    trade["profit_usdt"] = trade["amount"] * profit_pct / 100
                    trade["exit_reason"] = "take_profit"
                    closed.append(trade)
                    self.active_trades.remove(trade)
        
        for trade in closed:
            self.balance += trade["amount"] + trade.get("profit_usdt", 0)
            emoji = "??" if trade["profit_pct"] > 0 else "??"
            msg = f"{emoji} ЗАКРЫТА {trade['symbol']}: {trade['profit_pct']:+.2f}% | {trade['exit_reason']}"
            self.add_log(msg)
            self.send_telegram(msg)
            self.trade_history.append(trade)
        
        return closed
    
    def scan_all(self):
        """Сканирование всех монет"""
        signals = []
        for symbol in COINS:
            price = self.get_price(symbol)
            if price == 0:
                continue
            signal, confidence, reasons = self.analyze(symbol, price)
            if signal != "HOLD" and confidence > 60:
                signals.append({
                    "symbol": symbol,
                    "signal": signal,
                    "confidence": round(confidence),
                    "price": round(price, 2),
                    "reasons": reasons
                })
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
    
    def get_stats(self):
        wins = sum(1 for t in self.trade_history if t.get("profit_pct", 0) > 0)
        losses = len(self.trade_history) - wins
        win_rate = (wins / max(len(self.trade_history), 1)) * 100
        total_profit = sum(t.get("profit_usdt", 0) for t in self.trade_history)
        
        return {
            "balance": round(self.balance, 2),
            "total_profit": round(total_profit, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "total_trades": len(self.trade_history),
            "active_trades": len(self.active_trades),
            "auto_pilot": self.auto_pilot,
            "mode": self.mode,
            "uptime": str(datetime.now() - self.session_start).split('.')[0]
        }

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

bot = TradingBot()
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ABSOLUTE TRADING BOT</title>
    <meta http-equiv="refresh" content="3">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            font-family: 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            text-align: center;
            padding: 20px;
            border-bottom: 2px solid #0f0;
            margin-bottom: 20px;
        }
        .header h1 { font-size: 2em; text-shadow: 0 0 10px #0f0; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: rgba(0,0,0,0.7);
            border: 1px solid #0f0;
            border-radius: 10px;
            padding: 20px;
        }
        .card h3 {
            margin-bottom: 15px;
            border-left: 3px solid #0f0;
            padding-left: 10px;
        }
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #333;
        }
        .profit { color: #0f0; }
        .loss { color: #f00; }
        .signal-buy { color: #0f0; font-weight: bold; }
        .signal-sell { color: #f00; font-weight: bold; }
        .button {
            background: #0f0;
            color: #000;
            border: none;
            padding: 10px 20px;
            margin: 5px;
            cursor: pointer;
            font-weight: bold;
            border-radius: 5px;
        }
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
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>?? ABSOLUTE TRADING BOT</h1>
        <p>Нейросеть | Автопилот | Telegram</p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>?? ПОРТФЕЛЬ</h3>
            <div class="stat"><span>Баланс:</span><span id="balance">$0</span></div>
            <div class="stat"><span>Прибыль:</span><span id="profit">$0</span></div>
            <div class="stat"><span>Винрейт:</span><span id="winrate">0%</span></div>
            <div class="stat"><span>Сделок:</span><span id="trades">0</span></div>
            <div class="stat"><span>Активных:</span><span id="active">0</span></div>
        </div>

        <div class="card">
            <h3>?? УПРАВЛЕНИЕ</h3>
            <button class="button" onclick="sendCommand('auto')" id="auto_btn">?? АВТОПИЛОТ: ВКЛ</button>
            <div class="stat"><span>Режим:</span><span id="mode">TEST</span></div>
            <div class="stat"><span>Uptime:</span><span id="uptime">0</span></div>
        </div>
    </div>

    <div class="card">
        <h3>?? ЛУЧШИЕ СИГНАЛЫ</h3>
        <div id="signals">Загрузка...</div>
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
    async function sendCommand(cmd) {
        await fetch(`/api/${cmd}`);
        setTimeout(update, 500);
    }

    async function update() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            
            document.getElementById('balance').innerHTML = `$${data.balance}`;
            document.getElementById('profit').innerHTML = `$${data.total_profit}`;
            document.getElementById('profit').className = data.total_profit >= 0 ? 'profit' : 'loss';
            document.getElementById('winrate').innerHTML = `${data.win_rate}%`;
            document.getElementById('trades').innerHTML = data.total_trades;
            document.getElementById('active').innerHTML = data.active_trades;
            document.getElementById('mode').innerHTML = data.mode;
            document.getElementById('uptime').innerHTML = data.uptime;
            
            const autoBtn = document.getElementById('auto_btn');
            autoBtn.innerHTML = data.auto_pilot ? '?? АВТОПИЛОТ: ВКЛ' : '?? АВТОПИЛОТ: ВЫКЛ';
            
            let signalsHtml = '';
            if (data.signals && data.signals.length > 0) {
                data.signals.forEach(s => {
                    signalsHtml += `<div class="stat">
                        <span>${s.symbol}</span>
                        <span class="${s.signal === 'BUY' ? 'signal-buy' : 'signal-sell'}">${s.signal}</span>
                        <span>${s.confidence}%</span>
                        <span>$${s.price}</span>
                    </div>`;
                });
            } else {
                signalsHtml = '<div class="stat">Нет сильных сигналов</div>';
            }
            document.getElementById('signals').innerHTML = signalsHtml;
            
            const logsDiv = document.getElementById('logs');
            logsDiv.innerHTML = '';
            if (data.logs) {
                data.logs.slice(0, 20).forEach(log => {
                    logsDiv.innerHTML += `<div class="stat">[${log.time}] ${log.msg}</div>`;
                });
            }
        } catch(e) { console.error(e); }
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
    signals = bot.scan_all()
    stats = bot.get_stats()
    return jsonify({
        "balance": stats["balance"],
        "total_profit": stats["total_profit"],
        "win_rate": stats["win_rate"],
        "total_trades": stats["total_trades"],
        "active_trades": stats["active_trades"],
        "auto_pilot": stats["auto_pilot"],
        "mode": stats["mode"],
        "uptime": stats["uptime"],
        "signals": signals[:5],
        "logs": bot.logs[:30]
    })

@app.route('/api/auto')
def toggle_auto():
    bot.auto_pilot = not bot.auto_pilot
    bot.add_log(f"?? Автопилот: {'ВКЛЮЧЁН' if bot.auto_pilot else 'ВЫКЛЮЧЁН'}")
    bot.send_telegram(f"?? Автопилот: {'ВКЛЮЧЁН' if bot.auto_pilot else 'ВЫКЛЮЧЁН'}")
    return {"auto_pilot": bot.auto_pilot}

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def main():
    # Запуск веб-сервера
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True)
    web_thread.start()
    
    bot.add_log("?? Веб-интерфейс: http://localhost:5002")
    
    while True:
        try:
            # Сканируем рынок
            signals = bot.scan_all()
            
            # Автопилот - открываем сделки
            if bot.auto_pilot and signals:
                for sig in signals[:2]:  # максимум 2 новые сделки за цикл
                    if sig["confidence"] > 65:
                        bot.execute_trade(sig["symbol"], sig["signal"], sig["price"], sig["confidence"], sig["reasons"])
            
            # Обновляем сделки (стоп-лосс, тейк-профит)
            bot.update_trades()
            
            # Консольный вывод
            os.system('cls' if os.name == 'nt' else 'clear')
            stats = bot.get_stats()
            
            print("\n" + "=" * 70)
            print("   ?? ABSOLUTE TRADING BOT")
            print("   ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 70)
            print(f"\n   ?? {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   ?? БАЛАНС: ${stats['balance']:.2f}")
            print(f"   ?? ПРИБЫЛЬ: ${stats['total_profit']:.2f}")
            print(f"   ?? ВИНРЕЙТ: {stats['win_rate']}% | СДЕЛОК: {stats['total_trades']}")
            print(f"   ?? АВТОПИЛОТ: {'? ВКЛЮЧЁН' if stats['auto_pilot'] else '? ВЫКЛЮЧЕН'}")
            print(f"   ?? РЕЖИМ: {stats['mode']} | UPTIME: {stats['uptime']}")
            
            print(f"\n   ?? ЛУЧШИЕ СИГНАЛЫ:")
            for sig in signals[:5]:
                emoji = "??" if sig["signal"] == "BUY" else "??"
                print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | ${sig['price']:.0f}")
            
            print(f"\n   ?? АКТИВНЫХ СДЕЛОК: {stats['active_trades']}")
            for trade in bot.active_trades:
                print(f"      {trade['symbol']} {trade['side']} | ${trade['amount']:.0f} | {trade['confidence']}%")
            
            print("\n" + "=" * 70)
            print("   ?? КОМАНДЫ: [A] Автопилот  [S] Статус  [Q] Выход")
            print("=" * 70)
            
            # Обработка клавиш
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii').lower()
                if key == 'a':
                    bot.auto_pilot = not bot.auto_pilot
                    bot.add_log(f"?? Автопилот: {'ВКЛ' if bot.auto_pilot else 'ВЫКЛ'}")
                elif key == 's':
                    bot.add_log(f"?? Статус: Баланс ${stats['balance']:.2f}, Прибыль ${stats['total_profit']:.2f}, Сделок {stats['total_trades']}")
                elif key == 'q':
                    bot.add_log("?? Бот остановлен")
                    bot.send_telegram("?? Бот остановлен")
                    break
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            bot.add_log("?? Бот остановлен")
            break
        except Exception as e:
            bot.add_log(f"?? Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()