#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
?? ABSOLUTE TRADING BOT v12.0 - ВЕБ-ПАНЕЛЬ + АВТОПИЛОТ + ЗАЩИТА
?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
"""

import os
import sys
import time
import json
import sqlite3
import hashlib
import hmac
import requests
import threading
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

# Импорт модулей
from ai_explainable import ExplainableAI
from ultimate_arbitrage import UltimateArbitrage
from social_signals import SocialSignals
from futures_trading import FuturesTrading
from risk_manager import RiskManager

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================

LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'trading_bot.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# MEXC КЛИЕНТ
# ============================================================================

class MexcClient:
    def __init__(self):
        self.api_key = os.getenv("MEXC_API_KEY")
        self.api_secret = os.getenv("MEXC_API_SECRET")
        self.base_url = "https://api.mexc.com"
    
    def _generate_signature(self, params: str) -> str:
        return hmac.new(self.api_secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    
    def get_balance(self, asset: str = "USDT") -> float:
        try:
            timestamp = int(time.time() * 1000)
            params = f"timestamp={timestamp}"
            signature = self._generate_signature(params)
            headers = {"X-MEXC-APIKEY": self.api_key}
            response = requests.get(f"{self.base_url}/api/v3/account?{params}&signature={signature}", headers=headers, timeout=10)
            if response.status_code == 200:
                for b in response.json().get("balances", []):
                    if b.get("asset") == asset:
                        return float(b.get("free", 0))
            return 0.0
        except:
            return 0.0
    
    def get_ticker(self, symbol: str = "BTCUSDT") -> float:
        try:
            response = requests.get(f"{self.base_url}/api/v3/ticker/price?symbol={symbol}", timeout=10)
            if response.status_code == 200:
                return float(response.json().get("price", 0))
            return 0.0
        except:
            return 0.0
    
    def get_klines(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 100) -> List[float]:
        try:
            response = requests.get(f"{self.base_url}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=10)
            if response.status_code == 200:
                return [float(candle[4]) for candle in response.json()]
            return []
        except:
            return []

# ============================================================================
# БАЗА ДАННЫХ
# ============================================================================

class Database:
    def __init__(self, db_path="trading.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()
        logger.info("? База данных готова")
    
    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                strategy TEXT,
                symbol TEXT,
                side TEXT,
                price REAL,
                amount REAL,
                profit REAL,
                status TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS futures_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                type TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                amount REAL,
                leverage INTEGER,
                profit REAL,
                status TEXT
            )
        ''')
        self.conn.commit()
    
    def add_trade(self, trade: Dict):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO trades (timestamp, strategy, symbol, side, price, amount, profit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (trade.get("timestamp"), trade.get("strategy", "AI"), trade.get("symbol", "BTC/USDT"),
              trade.get("side"), trade.get("price"), trade.get("amount"), trade.get("profit", 0), trade.get("status")))
        self.conn.commit()
    
    def add_futures_trade(self, trade: Dict):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO futures_trades (timestamp, type, symbol, side, entry_price, exit_price, amount, leverage, profit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (trade.get("timestamp"), trade.get("type"), trade.get("symbol"),
              trade.get("side"), trade.get("entry_price"), trade.get("exit_price", 0),
              trade.get("amount"), trade.get("leverage"), trade.get("profit", 0), trade.get("status")))
        self.conn.commit()

# ============================================================================
# ВЕБ-СОСТОЯНИЕ (синхронизация с dashboard)
# ============================================================================

web_state = {
    "balance": 0.0,
    "price": 0.0,
    "daily_pnl": 0.0,
    "total_trades": 0,
    "futures_count": 0,
    "neural_accuracy": 0.0,
    "last_prediction": "hold",
    "confidence": 0,
    "last_action": "",
    "capital_protection": True,
    "positions": [],
    "futures": []
}

def update_web_state(bot):
    """Обновление состояния для веб-интерфейса"""
    web_state["balance"] = bot.balance_usdt
    web_state["price"] = bot.current_price if hasattr(bot, 'current_price') else 0
    web_state["neural_accuracy"] = bot.ai.neural_network.accuracy if hasattr(bot.ai, 'neural_network') else 0
    web_state["last_prediction"] = getattr(bot, 'last_neural_pred', 'hold')
    web_state["confidence"] = getattr(bot, 'last_neural_conf', 0)
    web_state["last_action"] = getattr(bot, 'last_action_msg', 'Ожидание...')
    web_state["futures"] = bot.futures.get_positions() if hasattr(bot, 'futures') else []
    web_state["futures_count"] = len(web_state["futures"])

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

class UltimateTradingBot:
    def __init__(self):
        self.db = Database()
        self.mexc = MexcClient()
        self.ai = ExplainableAI()
        self.arbitrage = UltimateArbitrage()
        self.social = SocialSignals()
        self.futures = FuturesTrading()
        self.risk = RiskManager()
        self.running = False
        self.auto_pilot = False
        self.balance_usdt = 0.0
        self.peak_balance = 0.0
        self.current_price = 0.0
        self.last_neural_pred = "hold"
        self.last_neural_conf = 0
        self.last_action_msg = ""
        
        self._update_balance()
        self.risk.update_balance(self.balance_usdt)
        self.peak_balance = self.balance_usdt
        
        logger.info("=" * 60)
        logger.info("?? ABSOLUTE TRADING BOT v12.0 - ВЕБ-ПАНЕЛЬ + АВТОПИЛОТ")
        logger.info("=" * 60)
        logger.info(f"?? Баланс: ${self.balance_usdt:.2f} USDT")
        logger.info(f"?? AI уровень риска: {self.ai.risk_level}/10")
        logger.info(f"??? Защита капитала: {'ВКЛ' if self.risk.is_protection_active else 'ВЫКЛ'}")
        logger.info("=" * 60)
    
    def _update_balance(self):
        self.balance_usdt = self.mexc.get_balance("USDT")
        if self.balance_usdt > self.peak_balance:
            self.peak_balance = self.balance_usdt
        self.risk.update_balance(self.balance_usdt)
        web_state["balance"] = self.balance_usdt
    
    def _send_telegram(self, message: str):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                            json={"chat_id": chat_id, "text": message}, timeout=5)
            except:
                pass
    
    def _check_protection(self) -> bool:
        """Проверка защиты капитала"""
        daily_check = self.risk.check_daily_loss(self.balance_usdt)
        if daily_check["protected"]:
            msg = f"??? ЗАЩИТА АКТИВИРОВАНА! {daily_check['reason']}"
            logger.warning(msg)
            self._send_telegram(msg)
            self.last_action_msg = msg
            self.running = False
            return False
        
        drawdown_check = self.risk.check_total_drawdown(self.balance_usdt, self.peak_balance)
        if drawdown_check["protected"]:
            msg = f"?? АВАРИЙНАЯ ОСТАНОВКА! {drawdown_check['reason']}"
            logger.error(msg)
            self._send_telegram(msg)
            self.last_action_msg = msg
            self.running = False
            return False
        
        return True
    
    def _execute_auto_trade(self, neural_pred: Dict, price: float):
        """Автоматическое исполнение сделок по сигналам нейросети"""
        if not self.auto_pilot:
            return
        
        if neural_pred["confidence"] < 70:
            return
        
        # Закрываем противоположные позиции если есть
        if neural_pred["prediction"] == "up":
            # Закрываем шорты если есть
            for i, pos in enumerate(self.futures.positions[:]):
                if pos["type"] == "short":
                    result = self.futures.close_position(i)
                    if result["success"]:
                        msg = f"?? Автопилот: закрыт SHORT, прибыль {result['profit_pct']:.1f}%"
                        logger.info(msg)
                        self._send_telegram(msg)
            
            # Открываем LONG
            if len(self.futures.positions) < 2:  # максимум 2 позиции
                amount = min(50, self.balance_usdt * 0.1)
                result = self.futures.open_long("BTCUSDT", amount, 5)
                if result["success"]:
                    msg = f"?? АВТОПИЛОТ: {result['message']}"
                    logger.info(msg)
                    self._send_telegram(msg)
                    self.last_action_msg = msg
                    self.db.add_futures_trade({
                        "timestamp": time.time(),
                        "type": "long",
                        "symbol": "BTCUSDT",
                        "side": "buy",
                        "entry_price": price,
                        "amount": amount,
                        "leverage": 5,
                        "status": "open"
                    })
        
        elif neural_pred["prediction"] == "down":
            # Закрываем лонги если есть
            for i, pos in enumerate(self.futures.positions[:]):
                if pos["type"] == "long":
                    result = self.futures.close_position(i)
                    if result["success"]:
                        msg = f"?? Автопилот: закрыт LONG, прибыль {result['profit_pct']:.1f}%"
                        logger.info(msg)
                        self._send_telegram(msg)
            
            # Открываем SHORT
            if len(self.futures.positions) < 2:
                amount = min(50, self.balance_usdt * 0.1)
                result = self.futures.open_short("BTCUSDT", amount, 5)
                if result["success"]:
                    msg = f"?? АВТОПИЛОТ: {result['message']}"
                    logger.info(msg)
                    self._send_telegram(msg)
                    self.last_action_msg = msg
                    self.db.add_futures_trade({
                        "timestamp": time.time(),
                        "type": "short",
                        "symbol": "BTCUSDT",
                        "side": "sell",
                        "entry_price": price,
                        "amount": amount,
                        "leverage": 5,
                        "status": "open"
                    })
    
    def run(self):
        """Основной цикл бота"""
        logger.info("?? Бот запущен. Анализирую рынок...")
        self.running = True
        
        while self.running:
            try:
                self.current_price = self.mexc.get_ticker()
                historical_prices = self.mexc.get_klines(limit=100)
                self._update_balance()
                
                if not historical_prices:
                    time.sleep(30)
                    continue
                
                # Проверка защиты капитала
                if not self._check_protection():
                    break
                
                # Нейросетевое предсказание
                neural_pred = self.ai.predict_with_neural_network(historical_prices)
                self.last_neural_pred = neural_pred["prediction"]
                self.last_neural_conf = neural_pred["confidence"]
                
                logger.info(f"?? Нейросеть: {neural_pred['prediction']} с уверенностью {neural_pred['confidence']:.1f}%")
                self.last_action_msg = f"?? Нейросеть предсказывает {neural_pred['prediction']} ({neural_pred['confidence']:.0f}%)"
                
                # Автоматическая торговля (если включена)
                self._execute_auto_trade(neural_pred, self.current_price)
                
                # AI анализ для объяснений
                analysis = self.ai.analyze_with_explanation(historical_prices)
                if analysis["signal"]:
                    explanation = self.ai.explain_decision(
                        analysis["signal"], 
                        self.current_price, 
                        analysis["reasons"]
                    )
                    logger.info(f"\n{explanation}")
                    self.last_action_msg = explanation[:200]
                
                # Арбитраж
                best_arb = self.arbitrage.get_best_opportunity()
                if best_arb and best_arb["net_profit_pct"] > 0.3:
                    logger.info(f"?? АРБИТРАЖ: {best_arb['net_profit_pct']:.2f}% прибыли")
                
                # Обновление веб-состояния
                update_web_state(self)
                
                # Статистика
                futures_positions = self.futures.get_positions()
                logger.info(f"?? BTC: ${self.current_price:.2f} | Баланс: ${self.balance_usdt:.2f} | Фьючерсов: {len(futures_positions)}")
                
                time.sleep(30)
                
            except KeyboardInterrupt:
                logger.info("?? Бот остановлен")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                time.sleep(10)
    
    def stop(self):
        self.running = False
    
    def set_auto_pilot(self, enabled: bool):
        self.auto_pilot = enabled
        logger.info(f"?? Автопилот: {'ВКЛЮЧЁН' if enabled else 'ВЫКЛЮЧЁН'}")
    
    def dashboard(self):
        """Консольное меню (альтернатива веб-интерфейсу)"""
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\n" + "=" * 70)
            print("?? ABSOLUTE TRADING BOT v12.0")
            print("=" * 70)
            print(f"?? {datetime.now().strftime('%Y-%Y-%m-%d %H:%M:%S')}")
            print(f"?? Баланс: ${self.balance_usdt:.2f} USDT")
            print(f"?? Цена BTC: ${self.current_price:.2f}")
            print(f"?? Режим: {'АВТОПИЛОТ' if self.auto_pilot else 'РУЧНОЙ'}")
            print(f"??? Защита капитала: {'ВКЛ' if self.risk.is_protection_active else 'ВЫКЛ'}")
            print("=" * 70)
            
            print("\n?? ВЕБ-ИНТЕРФЕЙС: http://localhost:5002")
            print("\nМЕНЮ:")
            print("  1. Запустить бота")
            print("  2. Остановить бота")
            print("  3. Включить/Выключить автопилот")
            print("  4. Проверить арбитраж")
            print("  5. Показать цены")
            print("  6. Выйти")
            print("=" * 70)
            
            choice = input("\nВыберите действие (1-6): ").strip()
            
            if choice == "1":
                threading.Thread(target=self.run, daemon=True).start()
                input("\n? Бот запущен! Нажмите Enter для продолжения...")
            elif choice == "2":
                self.stop()
                input("\n?? Бот остановлен! Нажмите Enter...")
            elif choice == "3":
                self.auto_pilot = not self.auto_pilot
                print(f"\n?? Автопилот: {'ВКЛЮЧЁН' if self.auto_pilot else 'ВЫКЛЮЧЁН'}")
                input("Нажмите Enter...")
            elif choice == "4":
                best = self.arbitrage.get_best_opportunity()
                if best:
                    print(f"\n?? ЛУЧШАЯ АРБИТРАЖНАЯ ВОЗМОЖНОСТЬ:")
                    print(f"   Купить: {best['buy_at']} по ${best['buy_price']:.2f}")
                    print(f"   Продать: {best['sell_at']} по ${best['sell_price']:.2f}")
                    print(f"   Прибыль: {best['net_profit_pct']:.2f}%")
                else:
                    print("\n?? Арбитражных возможностей нет")
                input("\nНажмите Enter...")
            elif choice == "5":
                prices = self.arbitrage.get_all_prices()
                print("\n?? ТЕКУЩИЕ ЦЕНЫ НА БИРЖАХ:")
                for name, price in list(prices.items())[:10]:
                    print(f"   {name}: ${price:.2f}")
                input("\nНажмите Enter...")
            elif choice == "6":
                print("?? Выход...")
                break

# ============================================================================
# ЗАПУСК (в отдельном потоке для веб-сервера)
# ============================================================================

if __name__ == "__main__":
    # Запуск веб-сервера в отдельном потоке
    try:
        from web_dashboard import start_web_server
        web_thread = threading.Thread(target=start_web_server, daemon=True)
        web_thread.start()
        print("?? Веб-интерфейс запущен на http://localhost:5002")
    except ImportError:
        print("?? Веб-модуль не найден, работаем в консольном режиме")
    
    # Запуск основного бота
    bot = UltimateTradingBot()
    bot.dashboard()