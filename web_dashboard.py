# -*- coding: utf-8 -*-
# web_dashboard.py - Р’РµР±-РїР°РЅРµР»СЊ СѓРїСЂР°РІР»РµРЅРёСЏ РґР»СЏ С‚РѕСЂРіРѕРІРѕРіРѕ Р±РѕС‚Р°
# рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

from flask import Flask, render_template_string, jsonify, request
import threading
import time
import json
import os
from datetime import datetime

app = Flask(__name__)

# Р“Р»РѕР±Р°Р»СЊРЅРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ Р±РѕС‚Р°
bot_state = {
    "running": False,
    "auto_pilot": False,
    "balance": 0.0,
    "price": 0.0,
    "positions": [],
    "futures": [],
    "neural_accuracy": 0.0,
    "daily_pnl": 0.0,
    "total_trades": 0,
    "last_action": "РћР¶РёРґР°РЅРёРµ РєРѕРјР°РЅРґ...",
    "capital_protection": True,
    "max_daily_loss": 5.0,
    "last_prediction": "hold",
    "confidence": 0
}

# РҐСЂР°РЅРёР»РёС‰Рµ Р»РѕРіРѕРІ
log_messages = []

def add_log(message, level="info"):
    """Р”РѕР±Р°РІРёС‚СЊ СЃРѕРѕР±С‰РµРЅРёРµ РІ Р»РѕРі"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_messages.insert(0, {"time": timestamp, "msg": message, "level": level})
    if len(log_messages) > 100:
        log_messages.pop()
    print(f"[{timestamp}] {message}")

# HTML С€Р°Р±Р»РѕРЅ РґР»СЏ РІРµР±-РёРЅС‚РµСЂС„РµР№СЃР°
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ABSOLUTE TRADING BOT v12.0</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            font-family: 'Segoe UI', monospace;
            color: #0f0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            text-align: center;
            padding: 20px;
            border-bottom: 2px solid #0f0;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 2em; text-shadow: 0 0 10px #0f0; }
        .header p { color: #888; margin-top: 10px; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: rgba(0,0,0,0.7);
            border: 1px solid #0f0;
            border-radius: 10px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }
        .card h3 {
            color: #0f0;
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
        .stat-label { color: #aaa; }
        .stat-value { font-weight: bold; color: #0f0; }
        .stat-value.danger { color: #f00; }
        .stat-value.warning { color: #ff0; }
        .button {
            background: #0f0;
            color: #000;
            border: none;
            padding: 10px 20px;
            margin: 5px;
            cursor: pointer;
            font-weight: bold;
            border-radius: 5px;
            transition: all 0.3s;
        }
        .button:hover { background: #0a0; transform: scale(1.02); }
        .button.danger { background: #f00; color: #fff; }
        .button.warning { background: #ff0; color: #000; }
        .button.primary { background: #00f; color: #fff; }
        .neural-bar {
            background: #333;
            height: 20px;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }
        .neural-fill {
            background: linear-gradient(90deg, #0f0, #0a0);
            height: 100%;
            width: 0%;
            transition: width 0.5s;
        }
        .log-panel {
            background: #000;
            height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
            padding: 10px;
            border-radius: 5px;
        }
        .log-entry { color: #0f0; margin: 2px 0; }
        .log-entry.error { color: #f00; }
        .log-entry.warning { color: #ff0; }
        .flex-buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 15px; }
        .status-active { color: #0f0; font-weight: bold; }
        .status-inactive { color: #f00; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>рџ¤– ABSOLUTE TRADING BOT</h1>
        <p>v12.0 | РќРµР№СЂРѕСЃРµС‚СЊ + Р¤СЊСЋС‡РµСЂСЃС‹ + РђРІС‚РѕРїРёР»РѕС‚ | DABRANSKI ULADZIMIR PETROVICH</p>
    </div>

    <div class="grid">
        <div class="card">
            <h3>рџ“Љ РЎРћРЎРўРћРЇРќРР• РЎРРЎРўР•РњР«</h3>
            <div class="stat"><span class="stat-label">Р‘Р°Р»Р°РЅСЃ USDT:</span><span class="stat-value" id="balance">$0.00</span></div>
            <div class="stat"><span class="stat-label">BTC Р¦РµРЅР°:</span><span class="stat-value" id="price">$0</span></div>
            <div class="stat"><span class="stat-label">PNL Р·Р° СЃРµРіРѕРґРЅСЏ:</span><span class="stat-value" id="daily_pnl">$0.00</span></div>
            <div class="stat"><span class="stat-label">Р’СЃРµРіРѕ СЃРґРµР»РѕРє:</span><span class="stat-value" id="total_trades">0</span></div>
            <div class="stat"><span class="stat-label">РђРєС‚РёРІРЅС‹С… С„СЊСЋС‡РµСЂСЃРѕРІ:</span><span class="stat-value" id="futures_count">0</span></div>
        </div>

        <div class="card">
            <h3>рџ§  РќР•Р™Р РћРЎР•РўР¬</h3>
            <div class="stat"><span class="stat-label">РўРѕС‡РЅРѕСЃС‚СЊ РјРѕРґРµР»Рё:</span><span class="stat-value" id="neural_acc">0.0%</span></div>
            <div class="neural-bar"><div class="neural-fill" id="neural_fill" style="width:0%"></div></div>
            <div class="stat"><span class="stat-label">РџРѕСЃР»РµРґРЅРµРµ РїСЂРµРґСЃРєР°Р·Р°РЅРёРµ:</span><span class="stat-value" id="last_prediction">вЂ”</span></div>
            <div class="stat"><span class="stat-label">РЈРІРµСЂРµРЅРЅРѕСЃС‚СЊ:</span><span class="stat-value" id="confidence">0%</span></div>
        </div>

        <div class="card">
            <h3>рџЋ® РЈРџР РђР’Р›Р•РќРР•</h3>
            <div class="flex-buttons">
                <button class="button" onclick="sendCommand('start')">в–¶пёЏ РЎРўРђР Рў</button>
                <button class="button danger" onclick="sendCommand('stop')">вЏ№пёЏ РЎРўРћРџ</button>
                <button class="button warning" id="auto_btn" onclick="toggleAuto()">рџ¤– РђР’РўРћРџРР›РћРў: Р’Р«РљР›</button>
            </div>
            <div class="flex-buttons">
                <button class="button primary" onclick="sendCommand('close_all')">рџ”’ Р—РђРљР Р«РўР¬ Р’РЎР• РџРћР—РР¦РР</button>
            </div>
            <div class="stat" style="margin-top:15px">
                <span class="stat-label">Р—Р°С‰РёС‚Р° РєР°РїРёС‚Р°Р»Р° (max loss 5%):</span>
                <span class="stat-value" id="protection_status">вњ… Р’РљР›</span>
            </div>
        </div>

        <div class="card">
            <h3>рџ“€ РћРўРљР Р«РўР«Р• РџРћР—РР¦РР</h3>
            <div id="positions_list">РќРµС‚ РѕС‚РєСЂС‹С‚С‹С… РїРѕР·РёС†РёР№</div>
        </div>

        <div class="card">
            <h3>вљЎ РђРљРўРР’РќР«Р• Р¤Р¬Р®Р§Р•Р РЎР«</h3>
            <div id="futures_list">РќРµС‚ Р°РєС‚РёРІРЅС‹С… С„СЊСЋС‡РµСЂСЃРѕРІ</div>
        </div>

        <div class="card">
            <h3>рџ¤– РџРћРЎР›Р•Р”РќР•Р• Р Р•РЁР•РќРР• AI</h3>
            <div id="last_action" class="log-panel" style="height:100px">РћР¶РёРґР°РЅРёРµ РґРµР№СЃС‚РІРёР№...</div>
        </div>
    </div>

    <div class="card">
        <h3>рџ“‹ LIVE Р›РћР“Р</h3>
        <div id="logs" class="log-panel"></div>
    </div>
</div>

<script>
    let autoPilot = false;

    async function fetchData() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            document.getElementById('balance').innerText = `$${data.balance.toFixed(2)}`;
            document.getElementById('price').innerText = `$${data.price.toFixed(2)}`;
            document.getElementById('daily_pnl').innerText = `$${data.daily_pnl.toFixed(2)}`;
            document.getElementById('total_trades').innerText = data.total_trades;
            document.getElementById('futures_count').innerText = data.futures_count;
            document.getElementById('neural_acc').innerText = `${data.neural_accuracy.toFixed(1)}%`;
            document.getElementById('neural_fill').style.width = `${data.neural_accuracy}%`;
            document.getElementById('last_prediction').innerHTML = data.last_prediction === 'up' ? 'рџџў Р’Р’Р•Р РҐ' : (data.last_prediction === 'down' ? 'рџ”ґ Р’РќРР—' : 'вљЄ РҐРћР›Р”');
            document.getElementById('confidence').innerText = `${data.confidence}%`;
            document.getElementById('last_action').innerHTML = `<div class="log-entry">${data.last_action}</div>`;
            document.getElementById('protection_status').innerHTML = data.capital_protection ? 'вњ… Р’РљР›' : 'вќЊ Р’Р«РљР›';
            
            let positionsHtml = '';
            if (data.positions.length === 0) {
                positionsHtml = 'РќРµС‚ РѕС‚РєСЂС‹С‚С‹С… РїРѕР·РёС†РёР№';
            } else {
                data.positions.forEach(p => {
                    positionsHtml += `<div class="stat"><span>${p.type} ${p.amount} BTC</span><span>${p.profit_pct}%</span></div>`;
                });
            }
            document.getElementById('positions_list').innerHTML = positionsHtml;
            
            let futuresHtml = '';
            if (data.futures.length === 0) {
                futuresHtml = 'РќРµС‚ Р°РєС‚РёРІРЅС‹С… С„СЊСЋС‡РµСЂСЃРѕРІ';
            } else {
                data.futures.forEach(f => {
                    futuresHtml += `<div class="stat"><span>${f.type.toUpperCase()} ${f.amount_usdt} USDT x${f.leverage}</span><span class="${f.profit_pct < 0 ? 'danger' : ''}">${f.profit_pct}%</span></div>`;
                });
            }
            document.getElementById('futures_list').innerHTML = futuresHtml;
            
            const logsDiv = document.getElementById('logs');
            logsDiv.innerHTML = '';
            data.logs.slice(0, 30).forEach(log => {
                const cls = log.level === 'error' ? 'error' : (log.level === 'warning' ? 'warning' : '');
                logsDiv.innerHTML += `<div class="log-entry ${cls}">[${log.time}] ${log.msg}</div>`;
            });
        } catch(e) { console.error(e); }
    }
    
    async function sendCommand(cmd) {
        await fetch('/api/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command: cmd})
        });
        setTimeout(fetchData, 500);
    }
    
    async function toggleAuto() {
        autoPilot = !autoPilot;
        await sendCommand(autoPilot ? 'auto_on' : 'auto_off');
        document.getElementById('auto_btn').innerText = autoPilot ? 'рџ¤– РђР’РўРћРџРР›РћРў: Р’РљР›' : 'рџ¤– РђР’РўРћРџРР›РћРў: Р’Р«РљР›';
    }
    
    setInterval(fetchData, 1000);
    fetchData();
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/state')
def get_state():
    return jsonify({
        "balance": bot_state["balance"],
        "price": bot_state["price"],
        "daily_pnl": bot_state["daily_pnl"],
        "total_trades": bot_state["total_trades"],
        "futures_count": len(bot_state["futures"]),
        "neural_accuracy": bot_state["neural_accuracy"],
        "last_prediction": bot_state["last_prediction"],
        "confidence": bot_state["confidence"],
        "last_action": bot_state["last_action"],
        "capital_protection": bot_state["capital_protection"],
        "positions": bot_state["positions"],
        "futures": bot_state["futures"],
        "logs": log_messages[:50]
    })

@app.route('/api/command', methods=['POST'])
def handle_command():
    data = request.json
    cmd = data.get('command')
    add_log(f"рџ“џ РџРѕР»СѓС‡РµРЅР° РєРѕРјР°РЅРґР°: {cmd}", "warning")
    
    if cmd == "start":
        bot_state["running"] = True
        add_log("рџљЂ Р‘РѕС‚ Р·Р°РїСѓС‰РµРЅ", "info")
    elif cmd == "stop":
        bot_state["running"] = False
        add_log("рџ›‘ Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ", "warning")
    elif cmd == "auto_on":
        bot_state["auto_pilot"] = True
        add_log("рџ¤– РђР’РўРћРџРР›РћРў РђРљРўРР’РР РћР’РђРќ", "warning")
    elif cmd == "auto_off":
        bot_state["auto_pilot"] = False
        add_log("рџ‘ЁвЂЌвњ€пёЏ РђРІС‚РѕРїРёР»РѕС‚ РѕС‚РєР»СЋС‡С‘РЅ, СЂСѓС‡РЅРѕР№ СЂРµР¶РёРј", "warning")
    elif cmd == "close_all":
        add_log("рџ”’ Р—Р°РєСЂС‹С‚РёРµ РІСЃРµС… РїРѕР·РёС†РёР№...", "danger")
        bot_state["positions"] = []
        bot_state["futures"] = []
    
    return jsonify({"status": "ok"})

def start_web_server():
    """Р—Р°РїСѓСЃРє РІРµР±-СЃРµСЂРІРµСЂР° РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ"""
    add_log("рџЊђ Р’РµР±-СЃРµСЂРІРµСЂ Р·Р°РїСѓС‰РµРЅ РЅР° http://localhost:5002", "info")
    app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False)

if __name__ == "__main__":
    start_web_server()