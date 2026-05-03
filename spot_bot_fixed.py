# -*- coding: utf-8 -*-
# spot_bot_fixed.py - ИСПРАВЛЕННАЯ ВЕРСИЯ С РАБОЧИМИ КОМАНДАМИ

import time
import requests
import hmac
import hashlib
import os
import sys
from datetime import datetime

# ============================================================================
# НОВЫЕ КЛЮЧИ
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
TRADE_SIZE = 5
MAX_POSITIONS = 3

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def sign(params_str):
    return hmac.new(MEXC_API_SECRET.encode(), params_str.encode(), hashlib.sha256).hexdigest()

def get_spot_balance():
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

def analyze_symbol(symbol, price):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30", timeout=5)
        if r.status_code == 200:
            candles = r.json()
            prices = [float(c[4]) for c in candles]
            if len(prices) > 14:
                gains, losses = [], []
                for i in range(1, len(prices[-15:])):
                    diff = prices[-i] - prices[-i-1]
                    if diff > 0:
                        gains.append(diff)
                    else:
                        losses.append(abs(diff))
                avg_gain = sum(gains) / 14 if gains else 0
                avg_loss = sum(losses) / 14 if losses else 0.001
                rsi = 100 - (100 / (1 + avg_gain / avg_loss))
                if rsi < 35:
                    conf = int(65 + (35 - rsi))
                    return "BUY", min(90, conf), round(rsi, 1)
                elif rsi > 65:
                    conf = int(65 + (rsi - 65))
                    return "SELL", min(90, conf), round(rsi, 1)
    except:
        pass
    return "HOLD", 50, 50

def spot_market_buy(symbol, usdt_amount):
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

def spot_market_sell(symbol, usdt_amount):
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

# ============================================================================
# ОСНОВНОЙ БОТ
# ============================================================================

print("\n" + "=" * 60)
print("   🤖 SPOT TRADING BOT - MEXC (ИСПРАВЛЕННЫЙ)")
print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
print("=" * 60)
print("\n💡 Для выхода нажми Ctrl+C ДВА РАЗА")
print("💡 Или просто закрой окно\n")

balance = get_spot_balance()
positions = []
auto_pilot = True
total_trades = 0
winning_trades = 0
total_profit = 0

print(f"💰 Баланс: ${balance:.2f}")
print("🚀 Бот запущен...\n")

try:
    while True:
        try:
            balance = get_spot_balance()
            
            # Сканируем сигналы
            signals = []
            for coin in COINS:
                price = get_price(coin)
                if price > 0:
                    signal, conf, rsi = analyze_symbol(coin, price)
                    if signal != "HOLD" and conf > 60:
                        signals.append({"symbol": coin, "signal": signal, "confidence": conf, "price": price, "rsi": rsi})
            
            signals.sort(key=lambda x: x["confidence"], reverse=True)
            
            # Автопилот
            if auto_pilot and signals and len(positions) < MAX_POSITIONS:
                for sig in signals[:2]:
                    if sig["signal"] == "BUY" and balance >= TRADE_SIZE:
                        if spot_market_buy(sig["symbol"], TRADE_SIZE):
                            balance -= TRADE_SIZE
                            positions.append({
                                "symbol": sig["symbol"],
                                "entry_price": sig["price"],
                                "amount": TRADE_SIZE,
                                "time": time.time()
                            })
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ ПОКУПКА {sig['symbol']}: ${TRADE_SIZE} по {sig['price']:.0f}")
                    else:
                        for pos in positions[:]:
                            if pos["symbol"] == sig["symbol"]:
                                if spot_market_sell(sig["symbol"], TRADE_SIZE):
                                    profit_pct = (sig["price"] - pos["entry_price"]) / pos["entry_price"] * 100
                                    profit_usdt = TRADE_SIZE * profit_pct / 100
                                    balance += TRADE_SIZE
                                    positions.remove(pos)
                                    total_trades += 1
                                    total_profit += profit_usdt
                                    if profit_pct > 0:
                                        winning_trades += 1
                                    emoji = "🎉" if profit_pct > 0 else "📉"
                                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {emoji} ПРОДАЖА {sig['symbol']}: {profit_pct:+.2f}% (+${profit_usdt:.2f})")
            
            # Очистка старых позиций
            now = time.time()
            positions = [p for p in positions if now - p["time"] < 7200]
            
            # Вывод в консоль
            os.system('cls' if os.name == 'nt' else 'clear')
            win_rate = (winning_trades / max(total_trades, 1)) * 100
            
            print("\n" + "=" * 60)
            print("   🤖 SPOT TRADING BOT - MEXC")
            print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
            print("=" * 60)
            print(f"\n   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n   💰 БАЛАНС: ${balance:.2f}")
            print(f"   📊 ПРИБЫЛЬ: ${total_profit:.2f}")
            print(f"   🏆 ВИНРЕЙТ: {win_rate:.0f}% | СДЕЛОК: {total_trades}")
            print(f"   🤖 АВТОПИЛОТ: {'✅ ВКЛ' if auto_pilot else '❌ ВЫКЛ'}")
            
            print(f"\n   🎯 ЛУЧШИЕ СИГНАЛЫ:")
            for sig in signals[:5]:
                emoji = "📈" if sig["signal"] == "BUY" else "📉"
                print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | RSI={sig['rsi']} | ${sig['price']:.0f}")
            
            print(f"\n   📊 АКТИВНЫХ ПОЗИЦИЙ: {len(positions)}")
            print("\n" + "=" * 60)
            print("   💡 ДЛЯ ВЫХОДА: Ctrl + C (два раза)")
            print("=" * 60)
            
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Бот остановлен пользователем")
            break
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(5)
            
except KeyboardInterrupt:
    print("\n🛑 Бот остановлен")

print("\n👋 До свидания!")