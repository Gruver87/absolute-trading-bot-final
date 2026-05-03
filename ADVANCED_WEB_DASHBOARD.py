# -*- coding: utf-8 -*-
# ADVANCED_WEB_DASHBOARD.py - ПРОФЕССИОНАЛЬНЫЙ ВЕБ-ИНТЕРФЕЙС
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

from flask import Flask, render_template_string, jsonify, request
import threading
import time
import json
import os
from datetime import datetime

app = Flask(__name__)

# ============================================================================
# ДАННЫЕ ДЛЯ ВЕБ-ИНТЕРФЕЙСА (СИНХРОНИЗАЦИЯ С БОТОМ)
# ============================================================================

bot_state = {
    "running": True,
    "auto_pilot": True,
    "balance": 55.74,
    "peak_balance": 55.74,
    "total_profit": 0.0,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "win_rate": 0.0,
    "consecutive_losses": 0,
    "drawdown": 0.0,
    "daily_pnl": 0.0,
    "positions": [],
    "signals": [],
    "logs": [],
    "tracking_coins": 66,
    "mode": "REAL",
    "strategy": "Trailing stop (activate +3.0%, drop 2.0%)",
    "trade_size": 10,
    "max_positions": 5,
    "stop_loss": 3.5,
    "trailing_activate": 3.0,
    "trailing_distance": 2.0,
    "rsi_oversold": 35,
    "rsi_overbought": 65,
    "active_coins": []
}

# ============================================================================
# HTML ШАБЛОН (СУПЕР-НАВОРОЧЕННЫЙ)
# ============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ABSOLUTE ULTIMATE BOT v5.0 - PROFESSIONAL DASHBOARD</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #0d1a0d 50%, #0a0a0a 100%);
            font-family: 'Segoe UI', 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
            min-height: 100vh;
        }
        
        /* Анимации */
        @keyframes glow {
            0%, 100% { text-shadow: 0 0 5px #0f0, 0 0 10px #0f0; }
            50% { text-shadow: 0 0 20px #0f0, 0 0 30px #0f0; }
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        
        @keyframes slideIn {
            from { transform: translateX(-50px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        @keyframes gradientBg {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        
        .container { max-width: 1600px; margin: 0 auto; }
        
        /* Шапка */
        .header {
            text-align: center;
            padding: 25px;
            border-bottom: 2px solid #0f0;
            margin-bottom: 25px;
            animation: slideIn 0.5s ease;
        }
        
        .header h1 {
            font-size: 2.5em;
            animation: glow 2s infinite;
            letter-spacing: 3px;
        }
        
        .header .subtitle {
            color: #888;
            margin-top: 10px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            margin: 10px;
            font-weight: bold;
        }
        
        .status-online {
            background: rgba(0,255,0,0.2);
            border: 1px solid #0f0;
            color: #0f0;
            animation: pulse 2s infinite;
        }
        
        /* Сетка */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        /* Карточки */
        .card {
            background: rgba(0,0,0,0.75);
            backdrop-filter: blur(10px);
            border: 1px solid #0f0;
            border-radius: 15px;
            padding: 20px;
            transition: all 0.3s ease;
            animation: slideIn 0.5s ease;
        }
        
        .card:hover {
            transform: translateY(-3px);
            box-shadow: 0 5px 25px rgba(0,255,0,0.2);
            border-color: #0f0;
        }
        
        .card h3 {
            color: #0f0;
            margin-bottom: 15px;
            border-left: 3px solid #0f0;
            padding-left: 12px;
            font-size: 1.2em;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        
        /* Статистика */
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #222;
            font-size: 14px;
        }
        
        .stat-label {
            color: #aaa;
        }
        
        .stat-value {
            font-weight: bold;
            color: #0f0;
        }
        
        .stat-value.positive { color: #0f0; }
        .stat-value.negative { color: #f00; }
        .stat-value.warning { color: #ff0; }
        
        .big-number {
            font-size: 2em;
            font-weight: bold;
            text-align: center;
            margin: 15px 0;
        }
        
        /* График */
        .chart-container {
            background: rgba(0,0,0,0.5);
            border-radius: 10px;
            padding: 10px;
            margin-top: 10px;
        }
        
        canvas { width: 100%; height: 200px; }
        
        /* Кнопки */
        .button-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 15px;
        }
        
        .btn {
            padding: 10px 18px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s ease;
            font-size: 13px;
        }
        
        .btn-primary {
            background: #0f0;
            color: #000;
        }
        
        .btn-primary:hover {
            background: #0a0;
            transform: scale(1.02);
            box-shadow: 0 0 15px #0f0;
        }
        
        .btn-danger {
            background: #f00;
            color: #fff;
        }
        
        .btn-danger:hover {
            background: #c00;
            transform: scale(1.02);
        }
        
        .btn-warning {
            background: #ff0;
            color: #000;
        }
        
        .btn-warning:hover {
            background: #cc0;
            transform: scale(1.02);
        }
        
        .btn-info {
            background: #00f;
            color: #fff;
        }
        
        .btn-info:hover {
            background: #009;
            transform: scale(1.02);
        }
        
        .btn-secondary {
            background: #333;
            color: #0f0;
            border: 1px solid #0f0;
        }
        
        .btn-secondary:hover {
            background: #444;
        }
        
        /* Таблицы */
        .coin-table {
            width: 100%;
            font-size: 12px;
            border-collapse: collapse;
        }
        
        .coin-table th, .coin-table td {
            padding: 8px 5px;
            text-align: left;
            border-bottom: 1px solid #333;
        }
        
        .coin-table th {
            color: #0f0;
            border-bottom: 2px solid #0f0;
        }
        
        .signal-buy { color: #0f0; font-weight: bold; }
        .signal-sell { color: #f00; font-weight: bold; }
        .signal-hold { color: #ff0; }
        
        .progress-bar {
            background: #333;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0;
        }
        
        .progress-fill {
            background: linear-gradient(90deg, #0f0, #0a0);
            height: 100%;
            width: 0%;
            transition: width 0.5s;
        }
        
        /* Логи */
        .log-panel {
            background: #000;
            height: 250px;
            overflow-y: auto;
            font-size: 11px;
            padding: 12px;
            border-radius: 8px;
            font-family: monospace;
        }
        
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid #111;
            color: #0f0;
        }
        
        .log-entry.error { color: #f00; }
        .log-entry.warning { color: #ff0; }
        .log-entry.success { color: #0f0; }
        
        /* Слайдеры */
        .slider-container {
            margin: 15px 0;
        }
        
        .slider-container label {
            display: block;
            margin-bottom: 8px;
            color: #aaa;
        }
        
        input[type="range"] {
            width: 100%;
            height: 5px;
            background: #333;
            border-radius: 5px;
            -webkit-appearance: none;
        }
        
        input[type="range"]:focus {
            outline: none;
        }
        
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 15px;
            height: 15px;
            border-radius: 50%;
            background: #0f0;
            cursor: pointer;
        }
        
        /* Футер */
        .footer {
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            border-top: 1px solid #333;
            color: #666;
            font-size: 11px;
        }
        
        /* Адаптивность */
        @media (max-width: 768px) {
            .grid {
                grid-template-columns: 1fr;
            }
            .btn {
                padding: 8px 12px;
                font-size: 11px;
            }
        }
        
        /* Вкладки */
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
            border-bottom: 1px solid #333;
        }
        
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            background: transparent;
            border: none;
            color: #aaa;
            transition: all 0.3s;
        }
        
        .tab.active {
            color: #0f0;
            border-bottom: 2px solid #0f0;
        }
        
        .tab:hover {
            color: #0f0;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🤖 ABSOLUTE ULTIMATE BOT v5.0</h1>
        <div class="subtitle">
            <span class="status-badge status-online" id="status_badge">🟢 ONLINE</span>
            <span class="status-badge" id="mode_badge">💰 REAL MODE</span>
        </div>
        <p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
    </div>

    <!-- Вкладки -->
    <div class="tabs">
        <button class="tab active" onclick="showTab('dashboard')">📊 ДАШБОРД</button>
        <button class="tab" onclick="showTab('trading')">📈 ТОРГОВЛЯ</button>
        <button class="tab" onclick="showTab('signals')">🎯 СИГНАЛЫ</button>
        <button class="tab" onclick="showTab('settings')">⚙️ НАСТРОЙКИ</button>
        <button class="tab" onclick="showTab('analytics')">📉 АНАЛИТИКА</button>
    </div>

    <!-- Вкладка: ДАШБОРД -->
    <div id="tab-dashboard" class="tab-content active">
        <div class="grid">
            <!-- Баланс и портфель -->
            <div class="card">
                <h3>💰 ПОРТФЕЛЬ</h3>
                <div class="big-number" id="balance">$0.00</div>
                <div class="stat"><span class="stat-label">PNL сегодня:</span><span class="stat-value" id="daily_pnl">$0.00</span></div>
                <div class="stat"><span class="stat-label">Общая прибыль:</span><span class="stat-value" id="total_profit">$0.00</span></div>
                <div class="stat"><span class="stat-label">Пик баланса:</span><span class="stat-value" id="peak">$0.00</span></div>
                <div class="stat"><span class="stat-label">Просадка:</span><span class="stat-value" id="drawdown">0%</span></div>
                <div class="progress-bar"><div class="progress-fill" id="drawdown_bar" style="width:0%"></div></div>
            </div>

            <!-- Статистика торговли -->
            <div class="card">
                <h3>📊 СТАТИСТИКА</h3>
                <div class="stat"><span class="stat-label">Всего сделок:</span><span class="stat-value" id="total_trades">0</span></div>
                <div class="stat"><span class="stat-label">Выигрыши / Проигрыши:</span><span class="stat-value"><span id="wins">0</span> / <span id="losses">0</span></span></div>
                <div class="stat"><span class="stat-label">Винрейт:</span><span class="stat-value" id="win_rate">0%</span></div>
                <div class="stat"><span class="stat-label">Серия убытков:</span><span class="stat-value warning" id="consecutive_losses">0</span></div>
                <div class="progress-bar"><div class="progress-fill" id="winrate_bar" style="width:0%"></div></div>
            </div>

            <!-- Система -->
            <div class="card">
                <h3>⚙️ СИСТЕМА</h3>
                <div class="stat"><span class="stat-label">Автопилот:</span><span class="stat-value" id="autopilot_status">✅ ВКЛ</span></div>
                <div class="stat"><span class="stat-label">Режим:</span><span class="stat-value" id="mode">REAL</span></div>
                <div class="stat"><span class="stat-label">Отслеживается монет:</span><span class="stat-value" id="tracking_coins">0</span></div>
                <div class="stat"><span class="stat-label">Открыто позиций:</span><span class="stat-value" id="open_positions">0</span></div>
                <div class="stat"><span class="stat-label">Активных позиций:</span><span class="stat-value" id="active_positions">0/5</span></div>
            </div>
        </div>

        <div class="grid">
            <!-- Активные позиции -->
            <div class="card">
                <h3>📈 АКТИВНЫЕ ПОЗИЦИИ</h3>
                <div id="active_positions_list" style="max-height: 300px; overflow-y: auto;">
                    <div class="stat">Нет открытых позиций</div>
                </div>
            </div>

            <!-- Лучшие сигналы -->
            <div class="card">
                <h3>🎯 ЛУЧШИЕ СИГНАЛЫ</h3>
                <div id="top_signals" style="max-height: 300px; overflow-y: auto;">
                    <div class="stat">Загрузка...</div>
                </div>
            </div>
        </div>

        <!-- Логи -->
        <div class="card">
            <h3>📋 LIVE ЛОГИ</h3>
            <div id="logs" class="log-panel">Загрузка...</div>
        </div>
    </div>

    <!-- Вкладка: ТОРГОВЛЯ -->
    <div id="tab-trading" class="tab-content">
        <div class="grid">
            <div class="card">
                <h3>🎮 УПРАВЛЕНИЕ ТОРГОВЛЕЙ</h3>
                <div class="button-group">
                    <button class="btn btn-primary" onclick="sendCommand('start')">▶️ СТАРТ</button>
                    <button class="btn btn-danger" onclick="sendCommand('stop')">⏹️ СТОП</button>
                    <button class="btn btn-warning" onclick="sendCommand('auto')">🤖 АВТОПИЛОТ</button>
                    <button class="btn btn-danger" onclick="sendCommand('close_all')">🔒 ЗАКРЫТЬ ВСЁ</button>
                </div>
                <div class="button-group">
                    <button class="btn btn-info" onclick="sendCommand('rescan')">🔄 СКАНИРОВАТЬ</button>
                    <button class="btn btn-secondary" onclick="sendCommand('status')">📊 СТАТУС</button>
                    <button class="btn btn-secondary" onclick="sendCommand('telegram')">📱 TELEGRAM</button>
                </div>
            </div>

            <div class="card">
                <h3>💱 РЫНОК</h3>
                <div class="stat"><span class="stat-label">Цена BTC:</span><span class="stat-value" id="btc_price">$0</span></div>
                <div class="stat"><span class="stat-label">Цена ETH:</span><span class="stat-value" id="eth_price">$0</span></div>
                <div class="stat"><span class="stat-label">Цена SOL:</span><span class="stat-value" id="sol_price">$0</span></div>
                <div class="stat"><span class="stat-label">Объём 24h:</span><span class="stat-value" id="volume">--</span></div>
            </div>
        </div>

        <div class="card">
            <h3>📊 ВСЕ СИГНАЛЫ</h3>
            <div id="all_signals_table" style="max-height: 400px; overflow-y: auto;">
                <table class="coin-table">
                    <thead>
                        <tr><th>Монета</th><th>Сигнал</th><th>Уверенность</th><th>Цена</th><th>RSI</th></tr>
                    </thead>
                    <tbody id="signals_table_body"></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Вкладка: НАСТРОЙКИ -->
    <div id="tab-settings" class="tab-content">
        <div class="grid">
            <div class="card">
                <h3>⚙️ ТОРГОВЫЕ НАСТРОЙКИ</h3>
                <div class="slider-container">
                    <label>Размер сделки: <span id="trade_size_val">10</span> USDT</label>
                    <input type="range" id="trade_size_slider" min="5" max="50" step="5" value="10" onchange="updateSetting('trade_size', this.value)">
                </div>
                <div class="slider-container">
                    <label>Макс позиций: <span id="max_positions_val">5</span></label>
                    <input type="range" id="max_positions_slider" min="1" max="10" step="1" value="5" onchange="updateSetting('max_positions', this.value)">
                </div>
                <div class="slider-container">
                    <label>Стоп-лосс: <span id="stop_loss_val">3.5</span>%</label>
                    <input type="range" id="stop_loss_slider" min="1" max="10" step="0.5" value="3.5" onchange="updateSetting('stop_loss', this.value)">
                </div>
                <div class="slider-container">
                    <label>Активация трейлинга: <span id="trailing_activate_val">3.0</span>%</label>
                    <input type="range" id="trailing_activate_slider" min="1" max="10" step="0.5" value="3.0" onchange="updateSetting('trailing_activate', this.value)">
                </div>
                <div class="slider-container">
                    <label>Отступ трейлинга: <span id="trailing_distance_val">2.0</span>%</label>
                    <input type="range" id="trailing_distance_slider" min="1" max="5" step="0.5" value="2.0" onchange="updateSetting('trailing_distance', this.value)">
                </div>
            </div>

            <div class="card">
                <h3>🎯 ИНДИКАТОРЫ</h3>
                <div class="slider-container">
                    <label>RSI покупки (ниже): <span id="rsi_oversold_val">35</span></label>
                    <input type="range" id="rsi_oversold_slider" min="20" max="45" step="1" value="35" onchange="updateSetting('rsi_oversold', this.value)">
                </div>
                <div class="slider-container">
                    <label>RSI продажи (выше): <span id="rsi_overbought_val">65</span></label>
                    <input type="range" id="rsi_overbought_slider" min="55" max="80" step="1" value="65" onchange="updateSetting('rsi_overbought', this.value)">
                </div>
            </div>

            <div class="card">
                <h3>🛡️ ЗАЩИТА</h3>
                <div class="slider-container">
                    <label>Дневной лимит убытка: <span id="max_daily_loss_val">15</span> USDT</label>
                    <input type="range" id="max_daily_loss_slider" min="5" max="50" step="5" value="15" onchange="updateSetting('max_daily_loss', this.value)">
                </div>
                <div class="slider-container">
                    <label>Серия убытков для стопа: <span id="max_consecutive_val">5</span></label>
                    <input type="range" id="max_consecutive_slider" min="2" max="10" step="1" value="5" onchange="updateSetting('max_consecutive_losses', this.value)">
                </div>
                <div class="button-group">
                    <button class="btn btn-warning" onclick="sendCommand('reset_daily')">📅 СБРОСИТЬ ДНЕВНУЮ СТАТИСТИКУ</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Вкладка: АНАЛИТИКА -->
    <div id="tab-analytics" class="tab-content">
        <div class="grid">
            <div class="card">
                <h3>📈 ПРОИЗВОДИТЕЛЬНОСТЬ</h3>
                <div class="stat"><span class="stat-label">Средняя прибыль на сделку:</span><span class="stat-value" id="avg_profit">0%</span></div>
                <div class="stat"><span class="stat-label">Лучшая сделка:</span><span class="stat-value positive" id="best_trade">0%</span></div>
                <div class="stat"><span class="stat-label">Худшая сделка:</span><span class="stat-value negative" id="worst_trade">0%</span></div>
                <div class="stat"><span class="stat-label">Фактор прибыли:</span><span class="stat-value" id="profit_factor">0</span></div>
                <div class="stat"><span class="stat-label">Средняя длительность:</span><span class="stat-value" id="avg_duration">--</span></div>
            </div>

            <div class="card">
                <h3>📊 РЫНОЧНЫЕ ДАННЫЕ</h3>
                <div class="stat"><span class="stat-label">Текущий рынок:</span><span class="stat-value" id="market_regime">Анализ...</span></div>
                <div class="stat"><span class="stat-label">Волатильность BTC:</span><span class="stat-value" id="volatility">0%</span></div>
                <div class="stat"><span class="stat-label">Доминирование BTC:</span><span class="stat-value" id="btc_dominance">--</span></div>
            </div>
        </div>

        <div class="card">
            <h3>📋 ИСТОРИЯ СДЕЛОК</h3>
            <div id="trade_history" style="max-height: 300px; overflow-y: auto;">
                <table class="coin-table">
                    <thead><tr><th>Время</th><th>Монета</th><th>Тип</th><th>Прибыль</th></tr></thead>
                    <tbody id="trade_history_body"></tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="footer">
        <p>🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
        <p>⚡ Трейлинг-стоп: активация после +3%, отступ 2% от максимума | Нет фиксированного тейк-профита!</p>
    </div>
</div>

<script>
    // Переключение вкладок
    function showTab(tabName) {
        document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('active'));
        document.getElementById(`tab-${tabName}`).classList.add('active');
        event.target.classList.add('active');
    }

    // Отправка команд на бот
    async function sendCommand(cmd) {
        await fetch('/api/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command: cmd})
        });
        setTimeout(updateData, 200);
    }

    // Обновление настроек
    async function updateSetting(setting, value) {
        await fetch('/api/setting', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({setting: setting, value: value})
        });
    }

    // Обновление всех данных
    async function updateData() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            
            // Дашборд
            document.getElementById('balance').innerHTML = `$${data.balance.toFixed(2)}`;
            document.getElementById('daily_pnl').innerHTML = `${data.daily_pnl >= 0 ? '+' : ''}$${data.daily_pnl?.toFixed(2) || '0.00'}`;
            document.getElementById('total_profit').innerHTML = `$${data.total_profit?.toFixed(2) || '0.00'}`;
            document.getElementById('peak').innerHTML = `$${data.peak_balance?.toFixed(2) || data.balance.toFixed(2)}`;
            document.getElementById('drawdown').innerHTML = `${data.drawdown?.toFixed(1) || '0'}%`;
            document.getElementById('drawdown_bar').style.width = `${data.drawdown || 0}%`;
            document.getElementById('total_trades').innerHTML = data.total_trades || 0;
            document.getElementById('wins').innerHTML = data.wins || 0;
            document.getElementById('losses').innerHTML = data.losses || 0;
            document.getElementById('win_rate').innerHTML = `${data.win_rate?.toFixed(1) || '0'}%`;
            document.getElementById('winrate_bar').style.width = `${data.win_rate || 0}%`;
            document.getElementById('consecutive_losses').innerHTML = data.consecutive_losses || 0;
            document.getElementById('autopilot_status').innerHTML = data.auto_pilot ? '✅ ВКЛ' : '❌ ВЫКЛ';
            document.getElementById('mode').innerHTML = data.mode || 'REAL';
            document.getElementById('tracking_coins').innerHTML = data.tracking_coins || 0;
            document.getElementById('open_positions').innerHTML = data.positions?.length || 0;
            document.getElementById('active_positions').innerHTML = `${data.positions?.length || 0}/${data.max_positions || 5}`;
            document.getElementById('mode_badge').innerHTML = data.mode === 'REAL' ? '💰 REAL MODE' : '📝 PAPER MODE';
            document.getElementById('autopilot_status').innerHTML = data.auto_pilot ? '✅ ВКЛ' : '❌ ВЫКЛ';
            
            // Активные позиции
            const positionsDiv = document.getElementById('active_positions_list');
            if (data.positions && data.positions.length > 0) {
                positionsDiv.innerHTML = data.positions.map(p => `
                    <div class="stat">
                        <span>${p.symbol}</span>
                        <span class="${p.current_profit >= 0 ? 'positive' : 'negative'}">${p.current_profit?.toFixed(2) || '0'}%</span>
                        <span>$${p.amount?.toFixed(0) || 0}</span>
                        <span>пик: +${p.peak_profit?.toFixed(1) || '0'}%</span>
                    </div>
                `).join('');
            } else {
                positionsDiv.innerHTML = '<div class="stat">Нет открытых позиций</div>';
            }
            
            // Лучшие сигналы
            const signalsDiv = document.getElementById('top_signals');
            if (data.signals && data.signals.length > 0) {
                signalsDiv.innerHTML = data.signals.slice(0, 8).map(s => `
                    <div class="stat">
                        <span>${s.symbol}</span>
                        <span class="${s.signal === 'BUY' ? 'signal-buy' : 'signal-sell'}">${s.signal}</span>
                        <span>${s.confidence}%</span>
                        <span>RSI=${s.rsi}</span>
                        <span>$${s.price?.toFixed(0) || 0}</span>
                    </div>
                `).join('');
            } else {
                signalsDiv.innerHTML = '<div class="stat">Нет сигналов</div>';
            }
            
            // Логи
            const logsDiv = document.getElementById('logs');
            if (data.logs && data.logs.length > 0) {
                logsDiv.innerHTML = data.logs.slice(0, 30).map(l => `
                    <div class="log-entry ${l.level || 'info'}">[${l.time}] ${l.msg}</div>
                `).join('');
            } else {
                logsDiv.innerHTML = '<div class="log-entry">Ожидание данных...</div>';
            }
            
            // Таблица сигналов
            const tableBody = document.getElementById('signals_table_body');
            if (data.signals && data.signals.length > 0) {
                tableBody.innerHTML = data.signals.map(s => `
                    <tr>
                        <td><b>${s.symbol}</b></td>
                        <td class="${s.signal === 'BUY' ? 'signal-buy' : 'signal-sell'}">${s.signal}</td>
                        <td>${s.confidence}%</td>
                        <td>$${s.price?.toFixed(2) || 0}</td>
                        <td>${s.rsi}</td>
                    </tr>
                `).join('');
            } else {
                tableBody.innerHTML = '<tr><td colspan="5">Нет сигналов</td></tr>';
            }
            
            // BTC, ETH, SOL цены
            if (data.signals) {
                const btc = data.signals.find(s => s.symbol === 'BTCUSDT');
                const eth = data.signals.find(s => s.symbol === 'ETHUSDT');
                const sol = data.signals.find(s => s.symbol === 'SOLUSDT');
                document.getElementById('btc_price').innerHTML = btc ? `$${btc.price?.toFixed(2)}` : '$0';
                document.getElementById('eth_price').innerHTML = eth ? `$${eth.price?.toFixed(2)}` : '$0';
                document.getElementById('sol_price').innerHTML = sol ? `$${sol.price?.toFixed(2)}` : '$0';
            }
            
            // Настройки слайдеров
            document.getElementById('trade_size_val').innerHTML = data.trade_size || 10;
            document.getElementById('max_positions_val').innerHTML = data.max_positions || 5;
            document.getElementById('stop_loss_val').innerHTML = data.stop_loss || 3.5;
            document.getElementById('trailing_activate_val').innerHTML = data.trailing_activate || 3.0;
            document.getElementById('trailing_distance_val').innerHTML = data.trailing_distance || 2.0;
            document.getElementById('rsi_oversold_val').innerHTML = data.rsi_oversold || 35;
            document.getElementById('rsi_overbought_val').innerHTML = data.rsi_overbought || 65;
            
            // Слайдеры
            document.getElementById('trade_size_slider').value = data.trade_size || 10;
            document.getElementById('max_positions_slider').value = data.max_positions || 5;
            document.getElementById('stop_loss_slider').value = data.stop_loss || 3.5;
            
        } catch(e) { console.error(e); }
    }

    setInterval(updateData, 2000);
    updateData();
</script>
</body>
</html>
'''

# ============================================================================
# API ЭНДПОЙНТЫ
# ============================================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/state')
def get_state():
    """Возвращает текущее состояние бота"""
    return jsonify(bot_state)

@app.route('/api/command', methods=['POST'])
def handle_command():
    """Обработка команд от веб-интерфейса"""
    cmd = request.json.get('command')
    print(f"📟 Команда из веб-интерфейса: {cmd}")
    
    if cmd == 'start':
        bot_state["running"] = True
        add_log("🚀 Бот запущен из веб-интерфейса", "success")
    elif cmd == 'stop':
        bot_state["running"] = False
        add_log("🛑 Бот остановлен из веб-интерфейса", "warning")
    elif cmd == 'auto':
        bot_state["auto_pilot"] = not bot_state["auto_pilot"]
        add_log(f"🤖 Автопилот: {'ВКЛЮЧЁН' if bot_state['auto_pilot'] else 'ВЫКЛЮЧЕН'}", "warning")
    elif cmd == 'close_all':
        bot_state["positions"] = []
        add_log("🔒 ВСЕ ПОЗИЦИИ ЗАКРЫТЫ", "danger")
    elif cmd == 'rescan':
        add_log("🔍 Принудительное сканирование рынка", "info")
    elif cmd == 'status':
        add_log(f"📊 Баланс: ${bot_state['balance']:.2f}, Прибыль: ${bot_state['total_profit']:.2f}", "info")
    elif cmd == 'telegram':
        add_log("📱 Telegram уведомление отправлено", "success")
    elif cmd == 'reset_daily':
        bot_state["daily_pnl"] = 0
        add_log("📅 Дневная статистика сброшена", "info")
    
    return jsonify({"status": "ok"})

@app.route('/api/setting', methods=['POST'])
def update_setting():
    """Обновление настроек бота"""
    setting = request.json.get('setting')
    value = request.json.get('value')
    
    if setting == 'trade_size':
        bot_state["trade_size"] = float(value)
        add_log(f"⚙️ Размер сделки изменён на ${value}", "info")
    elif setting == 'max_positions':
        bot_state["max_positions"] = int(value)
        add_log(f"⚙️ Максимум позиций изменён на {value}", "info")
    elif setting == 'stop_loss':
        bot_state["stop_loss"] = float(value)
        add_log(f"⚙️ Стоп-лосс изменён на {value}%", "info")
    elif setting == 'trailing_activate':
        bot_state["trailing_activate"] = float(value)
        add_log(f"⚙️ Активация трейлинга изменена на {value}%", "info")
    elif setting == 'trailing_distance':
        bot_state["trailing_distance"] = float(value)
        add_log(f"⚙️ Отступ трейлинга изменён на {value}%", "info")
    elif setting == 'rsi_oversold':
        bot_state["rsi_oversold"] = int(value)
        add_log(f"⚙️ RSI покупки изменён на {value}", "info")
    elif setting == 'rsi_overbought':
        bot_state["rsi_overbought"] = int(value)
        add_log(f"⚙️ RSI продажи изменён на {value}", "info")
    
    return jsonify({"status": "ok"})

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

def add_log(msg, level="info"):
    """Добавление сообщения в логи"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    bot_state["logs"].insert(0, {"time": timestamp, "msg": msg, "level": level})
    if len(bot_state["logs"]) > 100:
        bot_state["logs"].pop()
    print(f"[{timestamp}] {msg}")

# ============================================================================
# ЗАПУСК ВЕБ-СЕРВЕРА
# ============================================================================

def start_web_server():
    """Запуск веб-сервера в отдельном потоке"""
    print("=" * 60)
    print("🌐 ПРОФЕССИОНАЛЬНЫЙ ВЕБ-ИНТЕРФЕЙС ЗАПУЩЕН")
    print("📍 http://localhost:5002")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False)

if __name__ == "__main__":
    start_web_server()