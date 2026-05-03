# test_bot.py - ДИАГНОСТИКА БОТА
import requests
import hmac
import hashlib
import time
import json

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

print("=" * 60)
print("🔬 ДИАГНОСТИКА ТОРГОВОГО БОТА")
print("=" * 60)

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def test_api_connection():
    print("\n1️⃣ ТЕСТ API СОЕДИНЕНИЯ...")
    try:
        t = int(time.time() * 1000)
        sig = sign(f"timestamp={t}")
        resp = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                            headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if resp.status_code == 200:
            print("   ✅ API работает!")
            return True
        else:
            print(f"   ❌ Ошибка: {resp.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Исключение: {e}")
        return False

def test_get_balance():
    print("\n2️⃣ ТЕСТ ПОЛУЧЕНИЯ БАЛАНСА...")
    try:
        t = int(time.time() * 1000)
        sig = sign(f"timestamp={t}")
        resp = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                            headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for b in data.get("balances", []):
                if b.get("asset") == "USDT":
                    print(f"   ✅ Баланс: ${float(b.get('free', 0)):.2f}")
                    return float(b.get('free', 0))
        print("   ❌ Не удалось получить баланс")
        return 0
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return 0

def test_get_price(symbol):
    print(f"\n3️⃣ ТЕСТ ПОЛУЧЕНИЯ ЦЕНЫ {symbol}...")
    try:
        resp = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        if resp.status_code == 200:
            price = float(resp.json().get("price", 0))
            print(f"   ✅ Цена: ${price:.6f}")
            return price
        else:
            print(f"   ❌ Ошибка: {resp.status_code}")
            return 0
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return 0

def test_market_buy(symbol, amount_usd):
    print(f"\n4️⃣ ТЕСТ ПОКУПКИ {symbol} на ${amount_usd}...")
    price = test_get_price(symbol)
    if price == 0:
        print("   ❌ Нет цены, покупка невозможна")
        return False
    
    qty = amount_usd / price
    qty = round(qty, 8)
    print(f"   Количество: {qty} шт")
    
    if qty <= 0:
        print("   ❌ Слишком маленькое количество")
        return False
    
    t = int(time.time() * 1000)
    params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
    sig = sign(params)
    headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
    
    try:
        resp = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                             headers=headers, timeout=10)
        print(f"   Статус: {resp.status_code}")
        print(f"   Ответ: {resp.text[:200]}")
        if resp.status_code == 200:
            print("   ✅ ПОКУПКА УСПЕШНА!")
            return True
        else:
            print("   ❌ ОШИБКА ПОКУПКИ")
            return False
    except Exception as e:
        print(f"   ❌ Исключение: {e}")
        return False

def test_rsi_calculation():
    print("\n5️⃣ ТЕСТ РАСЧЁТА RSI...")
    try:
        resp = requests.get("https://api.mexc.com/api/v3/klines?symbol=SNXUSDT&interval=5m&limit=50", timeout=10)
        if resp.status_code == 200:
            prices = [float(c[4]) for c in resp.json()]
            print(f"   ✅ Получено свечей: {len(prices)}")
            
            # Простой RSI
            gains, losses = [], []
            for i in range(1, 15):
                diff = prices[-i] - prices[-i-1]
                if diff > 0:
                    gains.append(diff)
                else:
                    losses.append(abs(diff))
            avg_gain = sum(gains)/14 if gains else 0
            avg_loss = sum(losses)/14 if losses else 0.001
            rsi = 100 - (100/(1 + avg_gain/avg_loss))
            print(f"   📊 RSI SNXUSDT: {rsi:.1f}")
            
            if rsi < 35:
                print("   🟢 СИГНАЛ НА ПОКУПКУ!")
            else:
                print("   🔴 Сигнала нет")
            return rsi
        else:
            print(f"   ❌ Ошибка получения свечей")
            return 0
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return 0

def test_calculate_investment(balance):
    print("\n6️⃣ ТЕСТ РАСЧЁТА СУММЫ ПОКУПКИ...")
    BUDGET_SHARE = 0.2
    MIN_TRADE = 5
    invest = max(balance * BUDGET_SHARE, MIN_TRADE)
    print(f"   Баланс: ${balance:.2f}")
    print(f"   20% от баланса: ${balance * 0.2:.2f}")
    print(f"   Минимальная сделка: ${MIN_TRADE}")
    print(f"   Итоговая сумма: ${invest:.2f}")
    return invest

# ЗАПУСК ТЕСТОВ
print("\n" + "=" * 60)
print("ЗАПУСК ДИАГНОСТИКИ")
print("=" * 60)

# 1. API
if not test_api_connection():
    print("\n❌ API НЕ РАБОТАЕТ - ПРОВЕРЬ КЛЮЧИ И ИНТЕРНЕТ")
    exit()

# 2. Баланс
balance = test_get_balance()
if balance == 0:
    print("\n⚠️ БАЛАНС 0 - ПОПОЛНИ СЧЁТ")

# 3. Цена SNXUSDT
price = test_get_price("SNXUSDT")

# 4. RSI
rsi = test_rsi_calculation()

# 5. Сумма инвестиции
invest = test_calculate_investment(balance)

# 6. ТЕСТОВАЯ ПОКУПКА (спросим разрешения)
print("\n" + "=" * 60)
print("ТЕСТОВАЯ ПОКУПКА (только если RSI < 35)")
print("=" * 60)

if rsi < 35 and balance >= invest:
    print(f"✅ УСЛОВИЯ ВЫПОЛНЕНЫ!")
    print(f"   RSI={rsi:.1f} < 35")
    print(f"   Баланс ${balance:.2f} >= ${invest:.2f}")
    print("\n⚠️ ХОТИТЕ ВЫПОЛНИТЬ ТЕСТОВУЮ ПОКУПКУ?")
    answer = input("Введите 'yes' для покупки: ")
    if answer.lower() == 'yes':
        test_market_buy("SNXUSDT", invest)
    else:
        print("   Покупка отменена")
else:
    print(f"❌ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ")
    if rsi >= 35:
        print(f"   RSI={rsi:.1f} >= 35 - сигнала нет")
    if balance < invest:
        print(f"   Баланс ${balance:.2f} < ${invest:.2f} - мало денег")

print("\n" + "=" * 60)
print("ДИАГНОСТИКА ЗАВЕРШЕНА")
print("=" * 60)
