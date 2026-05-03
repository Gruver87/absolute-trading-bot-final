# -*- coding: utf-8 -*-
# real_bot.py - Р Р•РђР›Р¬РќРђРЇ РўРћР Р“РћР’Р›РЇ РќРђ MEXC
# рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
import random
import threading
import os
import msvcrt
import hashlib
import hmac
import requests
from datetime import datetime
from flask import Flask, jsonify, render_template_string

# ============================================================================
# РўР’РћР API РљР›Р®Р§Р (Р’РЎРўРђР’Р¬ РЎР’РћР!)
# ============================================================================

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"  # РўР’РћР™ API KEY
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"  # РўР’РћР™ SECRET

TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"
TELEGRAM_CHAT_ID = "1021048982"

# ============================================================================
# РќРђРЎРўР РћР™РљР
# ============================================================================

# РњРѕРЅРµС‚С‹ РґР»СЏ С‚РѕСЂРіРѕРІР»Рё (Р»РёРєРІРёРґРЅС‹Рµ, СЃ РјР°Р»РѕР№ РєРѕРјРёСЃСЃРёРµР№)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

# Р Р°Р·РјРµСЂС‹ РїРѕР·РёС†РёР№
SPOT_SIZE = 5      # $5 РЅР° СЃРґРµР»РєСѓ РІ СЃРїРѕС‚Рµ (С‡С‚РѕР±С‹ РЅРµ СЂРёСЃРєРѕРІР°С‚СЊ)
FUTURES_SIZE = 5   # $5 РЅР° СЃРґРµР»РєСѓ РІ С„СЊСЋС‡РµСЂСЃР°С…

# Р РёСЃРє-РјРµРЅРµРґР¶РјРµРЅС‚
STOP_LOSS_PCT = 2    # РЎС‚РѕРї-Р»РѕСЃСЃ 2%
TAKE_PROFIT_PCT = 4  # РўРµР№Рє-РїСЂРѕС„РёС‚ 4%
FUTURES_LEVERAGE = 3 # РџР»РµС‡Рѕ 3x (Р±РµР·РѕРїР°СЃРЅРѕ)

# ============================================================================
# MEXC API РљР›РР•РќРў
# ============================================================================

class MexcClient:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.mexc.com"
    
    def _sign(self, params_str):
        return hmac.new(self.api_secret.encode(), params_str.encode(), hashlib.sha256).hexdigest()
    
    def get_spot_balance(self):
        """РџРѕР»СѓС‡РёС‚СЊ СЃРїРѕС‚ Р±Р°Р»Р°РЅСЃ"""
        try:
            timestamp = int(time.time() * 1000)
            params = f"timestamp={timestamp}"
            signature = self._sign(params)
            
            headers = {"X-MEXC-APIKEY": self.api_key}
            url = f"{self.base_url}/api/v3/account?{params}&signature={signature}"
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for b in data.get("balances", []):
                    if b.get("asset") == "USDT":
                        return float(b.get("free", 0))
            return 0
        except Exception as e:
            return 0
    
    def get_futures_balance(self):
        """РџРѕР»СѓС‡РёС‚СЊ С„СЊСЋС‡РµСЂСЃ Р±Р°Р»Р°РЅСЃ"""
        try:
            timestamp = int(time.time() * 1000)
            params = f"timestamp={timestamp}"
            signature = self._sign(params)
            
            headers = {"X-MEXC-APIKEY": self.api_key}
            url = f"{self.base_url}/api/v3/futures/account?{params}&signature={signature}"
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return float(data.get("free", 0))
            return 0
        except:
            return 0
    
    def get_price(self, symbol):
        """РџРѕР»СѓС‡РёС‚СЊ С‚РµРєСѓС‰СѓСЋ С†РµРЅСѓ"""
        try:
            r = requests.get(f"{self.base_url}/api/v3/ticker/price?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                return float(r.json().get("price", 0))
        except:
            pass
        return 0
    
    def spot_buy(self, symbol, quantity_usdt):
        """РљСѓРїРёС‚СЊ РЅР° СЃРїРѕС‚Рµ"""
        try:
            price = self.get_price(symbol)
            if price == 0:
                return None
            
            quantity = quantity_usdt / price
            quantity = round(quantity, 6)
            
            timestamp = int(time.time() * 1000)
            params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
            signature = self._sign(params)
            
            headers = {"X-MEXC-APIKEY": self.api_key}
            url = f"{self.base_url}/api/v3/order?{params}&signature={signature}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            return None
    
    def spot_sell(self, symbol, quantity_usdt):
        """РџСЂРѕРґР°С‚СЊ РЅР° СЃРїРѕС‚Рµ"""
        try:
            price = self.get_price(symbol)
            if price == 0:
                return None
            
            quantity = quantity_usdt / price
            quantity = round(quantity, 6)
            
            timestamp = int(time.time() * 1000)
            params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
            signature = self._sign(params)
            
            headers = {"X-MEXC-APIKEY": self.api_key}
            url = f"{self.base_url}/api/v3/order?{params}&signature={signature}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()
            return None
        except:
            return None

# ============================================================================
# РћРЎРќРћР’РќРћР™ Р‘РћРў
# ============================================================================

class RealTradingBot:
    def __init__(self):
        self.mexc = MexcClient(MEXC_API_KEY, MEXC_API_SECRET)
        self.spot_balance = 0
        self.futures_balance = 0
        self.active_trades = []
        self.trade_history = []
        self.auto_pilot = True
        self.logs = []
        self.consecutive_losses = 0
        
        self.update_balances()
        self.add_log(f"рџљЂ Р Р•РђР›Р¬РќР«Р™ Р‘РћРў Р—РђРџРЈР©Р•Рќ")
        self.add_log(f"рџ’° РЎРїРѕС‚ Р±Р°Р»Р°РЅСЃ: ${self.spot_balance:.2f}")
        self.add_log(f"рџ’° Р¤СЊСЋС‡РµСЂСЃ Р±Р°Р»Р°РЅСЃ: ${self.futures_balance:.2f}")
        self.send_telegram(f"рџљЂ Р‘РћРў Р—РђРџРЈР©Р•Рќ! РЎРїРѕС‚: ${self.spot_balance}, Р¤СЊСЋС‡РµСЂСЃС‹: ${self.futures_balance}")
    
    def update_balances(self):
        self.spot_balance = self.mexc.get_spot_balance()
        self.futures_balance = self.mexc.get_futures_balance()
    
    def add_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.insert(0, {"time": timestamp, "msg": msg})
        if len(self.logs) > 100:
            self.logs.pop()
        print(f"[{timestamp}] {msg}")
    
    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[:400]}, timeout=3)
        except:
            pass
    
    def analyze(self, symbol, price):
        """РђРЅР°Р»РёР· СЂС‹РЅРєР° (СѓРїСЂРѕС‰С‘РЅРЅС‹Р№, РЅРѕ СЂР°Р±РѕС‡РёР№)"""
        # РџРѕР»СѓС‡Р°РµРј РёСЃС‚РѕСЂРёСЋ С†РµРЅ РґР»СЏ Р°РЅР°Р»РёР·Р°
        try:
            r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=50", timeout=5)
            if r.status_code == 200:
                candles = r.json()
                prices = [float(c[4]) for c in candles]
                
                if len(prices) > 20:
                    # RSI СѓРїСЂРѕС‰С‘РЅРЅС‹Р№
                    gains = []
                    losses = []
                    for i in range(1, len(prices[-15:])):
                        diff = prices[-i] - prices[-i-1]
                        if diff > 0:
                            gains.append(diff)
                        else:
                            losses.append(abs(diff))
                    
                    avg_gain = sum(gains) / 14 if gains else 0
                    avg_loss = sum(losses) / 14 if losses else 0.001
                    rsi = 100 - (100 / (1 + avg_gain / avg_loss))
                    
                    # SMA
                    sma5 = sum(prices[-5:]) / 5
                    sma20 = sum(prices[-20:]) / 20
                    
                    # РЎРёРіРЅР°Р»С‹
                    if rsi < 35 and sma5 > sma20:
                        confidence = int(65 + (35 - rsi))
                        return "BUY", min(90, confidence), [f"RSI={rsi:.0f}", "Р‘С‹С‡РёР№ С‚СЂРµРЅРґ"]
                    elif rsi > 65 and sma5 < sma20:
                        confidence = int(65 + (rsi - 65))
                        return "SELL", min(90, confidence), [f"RSI={rsi:.0f}", "РњРµРґРІРµР¶РёР№ С‚СЂРµРЅРґ"]
        except:
            pass
        
        return "HOLD", 50, ["Р С‹РЅРѕРє СЃС‚Р°Р±РёР»РµРЅ"]
    
    def execute_spot_trade(self, symbol, side, price, confidence):
        """РСЃРїРѕР»РЅРµРЅРёРµ СЃРґРµР»РєРё РЅР° СЃРїРѕС‚Рµ"""
        if not self.auto_pilot:
            return None
        
        if side == "BUY":
            if self.spot_balance >= SPOT_SIZE:
                result = self.mexc.spot_buy(symbol, SPOT_SIZE)
                if result:
                    self.spot_balance -= SPOT_SIZE
                    trade = {
                        "symbol": symbol, "side": side, "price": price,
                        "amount": SPOT_SIZE, "mode": "SPOT", "confidence": confidence,
                        "entry_time": time.time()
                    }
                    self.active_trades.append(trade)
                    self.add_log(f"вњ… REAL SPOT {side} {symbol}: ${SPOT_SIZE} РїРѕ ${price:.0f}")
                    self.send_telegram(f"вњ… SPOT {side} {symbol}: ${SPOT_SIZE}")
                    return trade
        else:
            # SELL - РЅСѓР¶РЅРѕ РёСЃРєР°С‚СЊ РїРѕР·РёС†РёСЋ РґР»СЏ Р·Р°РєСЂС‹С‚РёСЏ
            for trade in self.active_trades[:]:
                if trade["symbol"] == symbol and trade["mode"] == "SPOT" and trade["side"] == "BUY":
                    result = self.mexc.spot_sell(symbol, SPOT_SIZE)
                    if result:
                        profit_pct = (price - trade["price"]) / trade["price"] * 100
                        self.active_trades.remove(trade)
                        self.spot_balance += SPOT_SIZE
                        self.add_log(f"вњ… REAL SPOT SELL {symbol}: РїСЂРёР±С‹Р»СЊ {profit_pct:+.2f}%")
                        return trade
        return None
    
    def run(self):
        self.add_log("рџ”„ Р‘РѕС‚ РЅР°С‡Р°Р» Р°РЅР°Р»РёР· СЂС‹РЅРєР°...")
        
        while True:
            try:
                self.update_balances()
                
                # РЎРєР°РЅРёСЂСѓРµРј РјРѕРЅРµС‚С‹
                signals = []
                for symbol in COINS:
                    price = self.mexc.get_price(symbol)
                    if price == 0:
                        continue
                    signal, confidence, reasons = self.analyze(symbol, price)
                    if signal != "HOLD" and confidence > 65:
                        signals.append({
                            "symbol": symbol, "signal": signal,
                            "confidence": confidence, "price": price
                        })
                
                signals.sort(key=lambda x: x["confidence"], reverse=True)
                
                # РђРІС‚РѕРїРёР»РѕС‚
                if self.auto_pilot and signals:
                    for sig in signals[:2]:
                        self.execute_spot_trade(sig["symbol"], sig["signal"], sig["price"], sig["confidence"])
                
                # РљРѕРЅСЃРѕР»СЊ
                os.system('cls' if os.name == 'nt' else 'clear')
                print("\n" + "=" * 70)
                print("   рџљЂ REAL TRADING BOT - MEXC")
                print("   рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
                print("=" * 70)
                print(f"\n   рџ“… {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"\n   рџ’° РЎРџРћРў Р‘РђР›РђРќРЎ: ${self.spot_balance:.2f}")
                print(f"   вљЎ Р¤Р¬Р®Р§Р•Р РЎ Р‘РђР›РђРќРЎ: ${self.futures_balance:.2f}")
                print(f"   рџ¤– РђР’РўРћРџРР›РћРў: {'вњ… Р’РљР›' if self.auto_pilot else 'вќЊ Р’Р«РљР›'}")
                
                print(f"\n   рџЋЇ Р›РЈР§РЁРР• РЎРР“РќРђР›Р«:")
                for sig in signals[:5]:
                    emoji = "рџ“€" if sig["signal"] == "BUY" else "рџ“‰"
                    print(f"      {emoji} {sig['symbol']}: {sig['signal']} ({sig['confidence']}%) | ${sig['price']:.0f}")
                
                print(f"\n   рџ“Љ РђРљРўРР’РќР«РҐ РЎР”Р•Р›РћРљ: {len(self.active_trades)}")
                
                print("\n" + "=" * 70)
                print("   рџЋ® РљРћРњРђРќР”Р«: [A] РђРІС‚РѕРїРёР»РѕС‚  [S] РЎС‚Р°С‚СѓСЃ  [Q] Р’С‹С…РѕРґ")
                print("=" * 70)
                
                if msvcrt.kbhit():
                    key = msvcrt.getch().decode('ascii').lower()
                    if key == 'a':
                        self.auto_pilot = not self.auto_pilot
                        self.add_log(f"рџ¤– РђРІС‚РѕРїРёР»РѕС‚: {'Р’РљР›' if self.auto_pilot else 'Р’Р«РљР›'}")
                    elif key == 's':
                        self.add_log(f"рџ“Љ РЎРїРѕС‚: ${self.spot_balance}, Р¤СЊСЋС‡РµСЂСЃС‹: ${self.futures_balance}")
                    elif key == 'q':
                        self.add_log("рџ›‘ Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ")
                        break
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.add_log(f"вљ пёЏ РћС€РёР±РєР°: {e}")
                time.sleep(5)

# ============================================================================
# Р—РђРџРЈРЎРљ
# ============================================================================

if __name__ == "__main__":
    bot = RealTradingBot()
    bot.run()