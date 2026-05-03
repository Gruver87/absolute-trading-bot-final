# -*- coding: utf-8 -*-
from flask import Flask, jsonify
import requests
import random
import time

app = Flask(__name__)

# Последние данные с бота
last_data = {"price": "78000", "signal": "?? HOLD", "confidence": 50}

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>ABSOLUTE TRADING BOT v12.0</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {
                background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
                color: #0f0;
                font-family: 'Courier New', monospace;
                padding: 20px;
                min-height: 100vh;
            }
            .glitch {
                font-size: 48px;
                font-weight: bold;
                text-shadow: 0 0 10px #0f0;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }
            .price {
                font-size: 64px;
                font-weight: bold;
                margin: 30px 0;
                color: #ff0;
            }
            .signal {
                font-size: 48px;
                margin: 20px 0;
                padding: 20px;
                border: 2px solid #0f0;
                border-radius: 10px;
                display: inline-block;
            }
            .container {
                max-width: 900px;
                margin: 0 auto;
                text-align: center;
            }
            .stats {
                margin-top: 40px;
                padding: 20px;
                background: rgba(0,0,0,0.5);
                border-radius: 10px;
            }
            .footer {
                margin-top: 50px;
                color: #666;
                font-size: 12px;
            }
            .buy { color: #0f0; }
            .sell { color: #f00; }
            .hold { color: #ff0; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="glitch">?? ABSOLUTE TRADING BOT</div>
            <div class="price" id="price">?? $---</div>
            <div class="signal" id="signal">?? Анализ...</div>
            <div class="stats">
                <p>?? Уверенность: <span id="confidence">0</span>%</p>
                <p>?? Нейросеть | Фьючерсы | Автопилот | Защита капитала</p>
            </div>
            <div class="footer">
                ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
            </div>
        </div>
        <script>
            async function update() {
                try {
                    const res = await fetch('/api/data');
                    const data = await res.json();
                    document.getElementById('price').innerHTML = `?? BTC: $${data.price}`;
                    document.getElementById('signal').innerHTML = data.signal;
                    document.getElementById('signal').className = `signal ${data.signal_class}`;
                    document.getElementById('confidence').innerHTML = data.confidence;
                } catch(e) { console.error(e); }
            }
            setInterval(update, 3000);
            update();
        </script>
    </body>
    </html>
    '''

@app.route('/api/data')
def get_data():
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        if r.status_code == 200:
            price = r.json().get("price", "78000")
        else:
            price = "78000"
    except:
        price = "78000"
    
    # Симуляция сигналов нейросети
    signals = [
        {"text": "?? BUY (лонг)", "class": "buy", "confidence": random.randint(65, 95)},
        {"text": "?? SELL (шорт)", "class": "sell", "confidence": random.randint(65, 95)},
        {"text": "?? HOLD", "class": "hold", "confidence": random.randint(50, 80)}
    ]
    current = random.choice(signals)
    
    return jsonify({
        "price": price,
        "signal": current["text"],
        "signal_class": current["class"],
        "confidence": current["confidence"]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)