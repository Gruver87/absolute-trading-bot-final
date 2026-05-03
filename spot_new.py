# -*- coding: utf-8 -*-
import time
import requests
import hmac
import hashlib
import os
from datetime import datetime

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
TRADE_SIZE = 5

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_balance():
    try:
        t = int(time.time()*1000)
        s = sign(f"timestamp={t}")
        r = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={s}", 
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            for b in r.json().get("balances",[]):
                if b.get("asset")=="USDT":
                    return float(b.get("free",0))
    except: pass
    return 0

def get_price(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
        if r.status_code==200:
            return float(r.json().get("price",0))
    except: pass
    return 0

def analyze(s, p):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={s}&interval=5m&limit=30", timeout=5)
        if r.status_code==200:
            prices = [float(c[4]) for c in r.json()]
            if len(prices)>14:
                gains,losses=[],[]
                for i in range(1,len(prices[-15:])):
                    d = prices[-i] - prices[-i-1]
                    if d>0: gains.append(d)
                    else: losses.append(abs(d))
                ag = sum(gains)/14 if gains else 0
                al = sum(losses)/14 if losses else 0.001
                rsi = 100 - (100/(1+ag/al))
                if rsi<35: return "BUY", min(90, int(65+(35-rsi))), round(rsi,1)
                if rsi>65: return "SELL", min(90, int(65+(rsi-65))), round(rsi,1)
    except: pass
    return "HOLD",50,50

def buy(s, amt):
    try:
        p = get_price(s)
        if p==0: return False
        q = round(amt/p,6)
        t = int(time.time()*1000)
        params = f"symbol={s}&side=BUY&type=MARKET&quantity={q}&timestamp={t}"
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sign(params)}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code==200
    except: return False

def sell(s, amt):
    try:
        p = get_price(s)
        if p==0: return False
        q = round(amt/p,6)
        t = int(time.time()*1000)
        params = f"symbol={s}&side=SELL&type=MARKET&quantity={q}&timestamp={t}"
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sign(params)}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code==200
    except: return False

print("="*60)
print("   🤖 SPOT BOT (НОВЫЙ КЛЮЧ)")
print("   🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
print("="*60)

balance = get_balance()
positions = []
auto = True
trades = 0
wins = 0
profit = 0

print(f"💰 Баланс: ${balance:.2f}")
print("🚀 Бот запущен. Для выхода Ctrl+C\n")

try:
    while True:
        balance = get_balance()
        signals = []
        for coin in COINS:
            p = get_price(coin)
            if p>0:
                sig,conf,rsi = analyze(coin,p)
                if sig!="HOLD" and conf>60:
                    signals.append({"symbol":coin,"signal":sig,"conf":conf,"price":p,"rsi":rsi})
        signals.sort(key=lambda x: x["conf"], reverse=True)
        
        if auto and signals and len(positions)<3:
            for sig in signals[:2]:
                if sig["signal"]=="BUY" and balance>=TRADE_SIZE:
                    if buy(sig["symbol"],TRADE_SIZE):
                        balance-=TRADE_SIZE
                        positions.append({"symbol":sig["symbol"],"entry":sig["price"],"time":time.time()})
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ ПОКУПКА {sig['symbol']} ${TRADE_SIZE}")
                else:
                    for pos in positions[:]:
                        if pos["symbol"]==sig["symbol"]:
                            if sell(sig["symbol"],TRADE_SIZE):
                                pct = (sig["price"]-pos["entry"])/pos["entry"]*100
                                usd = TRADE_SIZE*pct/100
                                balance+=TRADE_SIZE
                                positions.remove(pos)
                                trades+=1
                                profit+=usd
                                if pct>0: wins+=1
                                emoji="🎉" if pct>0 else "📉"
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] {emoji} ПРОДАЖА {sig['symbol']}: {pct:+.2f}%")
        
        positions = [p for p in positions if time.time()-p["time"]<7200]
        
        os.system('cls')
        print("\n"+"="*60)
        print("   🤖 SPOT BOT - MEXC")
        print("="*60)
        print(f"\n   💰 БАЛАНС: ${balance:.2f}")
        print(f"   📊 ПРИБЫЛЬ: ${profit:.2f}")
        print(f"   🏆 ВИНРЕЙТ: {(wins/max(trades,1))*100:.0f}% | СДЕЛОК: {trades}")
        print(f"\n   🎯 СИГНАЛЫ:")
        for sig in signals[:5]:
            e="📈" if sig["signal"]=="BUY" else "📉"
            print(f"      {e} {sig['symbol']}: {sig['signal']} ({sig['conf']}%) | ${sig['price']:.0f}")
        print(f"\n   📊 ПОЗИЦИЙ: {len(positions)}")
        print("\n"+"="*60)
        print("   💡 Ctrl+C - выход")
        print("="*60)
        time.sleep(10)
except KeyboardInterrupt:
    print("\n🛑 ОСТАНОВЛЕНО")
