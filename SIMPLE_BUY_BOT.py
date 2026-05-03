# -*- coding: utf-8 -*-
# SIMPLE_BUY_BOT.py - ПРОСТОЙ БОТ ДЛЯ ПОКУПОК

import time
import requests
import hmac
import hashlib
from datetime import datetime

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except: pass
    return 0

def buy(symbol, usdt):
    price = get_price(symbol)
    if price == 0:
        print(f"❌ Нет цены {symbol}")
        return False
    qty = round(usdt / price, 8)
    if qty < 0.00000001:
        print(f"❌ Слишком мало {symbol}")
        return False
    t = int(time.time() * 1000)
    params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
    sig = sign(params)
    headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
    url = f"https://api.mexc.com/api/v3/order?{params}&signature={sig}"
    r = requests.post(url, headers=headers, timeout=10)
    if r.status_code == 200:
        print(f"✅ КУПИЛ {symbol}: {qty} шт за ${usdt}")
        return True
    else:
        print(f"❌ Ошибка: {r.status_code} - {r.text}")
        return False

print("=" * 50)
print("   ПРОСТОЙ БОТ ДЛЯ ПОКУПКИ")
print("=" * 50)
print(f"Баланс: $45.74")

while True:
    print("\nКОМАНДЫ:")
    print("  1 - Купить GALAUSDT ($5)")
    print("  2 - Купить OPUSDT ($5)")
    print("  3 - Купить DOGEUSDT ($5)")
    print("  4 - Выйти")
    
    choice = input("Выберите действие: ").strip()
    
    if choice == "1":
        buy("GALAUSDT", 5)
    elif choice == "2":
        buy("OPUSDT", 5)
    elif choice == "3":
        buy("DOGEUSDT", 5)
    elif choice == "4":
        print("Выход...")
        break
    else:
        print("Неверный выбор")
