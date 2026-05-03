# test_bot_fixed.py - ИСПРАВЛЕННЫЙ ТЕСТ (целое количество)
import requests
import hmac
import hashlib
import time

MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"
MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"

print("=" * 60)
print("🔬 ДИАГНОСТИКА (ИСПРАВЛЕННАЯ)")
print("=" * 60)

def sign(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_price(s):
    r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=5)
    return float(r.json().get("price", 0))

def get_balance():
    t = int(time.time() * 1000)
    sig = sign(f"timestamp={t}")
    r = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                     headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
    if r.status_code == 200:
        for b in r.json().get("balances", []):
            if b.get("asset") == "USDT":
                return float(b.get("free", 0))
    return 0

def buy_with_integer_quantity(symbol, max_usdt):
    """Покупка с ЦЕЛЫМ количеством монет"""
    price = get_price(symbol)
    if price == 0:
        print(f"   ❌ Нет цены")
        return False
    
    # Рассчитываем целое количество
    qty = int(max_usdt / price)
    if qty < 1:
        print(f"   ❌ Не хватает даже на 1 монету (нужно ${price:.6f})")
        return False
    
    actual_usdt = qty * price
    print(f"   Цена: ${price:.6f}")
    print(f"   Целое количество: {qty} шт")
    print(f"   Фактическая сумма: ${actual_usdt:.2f}")
    
    t = int(time.time() * 1000)
    params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
    sig = sign(params)
    headers = {"X-MEXC-APIKEY": MEXC_API_KEY}
    
    try:
        resp = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                             headers=headers, timeout=10)
        print(f"   Статус: {resp.status_code}")
        print(f"   Ответ: {resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

# Получаем баланс и цену
balance = get_balance()
price = get_price("SNXUSDT")

print(f"\n💰 Баланс: ${balance:.2f}")
print(f"💹 Цена SNXUSDT: ${price:.6f}")

# Рассчитываем максимальное целое количество
max_qty = int(balance / price)
actual_cost = max_qty * price
remaining = balance - actual_cost

print(f"\n📊 РАСЧЁТ:")
print(f"   Макс целых монет: {max_qty} шт")
print(f"   Стоимость: ${actual_cost:.2f}")
print(f"   Останется: ${remaining:.2f}")

if max_qty >= 1:
    print(f"\n✅ МОЖНО КУПИТЬ {max_qty} монет SNXUSDT за ${actual_cost:.2f}")
    answer = input("\nКупить? (yes/no): ")
    if answer.lower() == 'yes':
        print("\n4️⃣ ТЕСТ ПОКУПКИ С ЦЕЛЫМ КОЛИЧЕСТВОМ...")
        buy_with_integer_quantity("SNXUSDT", balance)
    else:
        print("Покупка отменена")
else:
    print(f"\n❌ НЕ ХВАТАЕТ ДАЖЕ НА 1 МОНЕТУ! Нужно ${price:.6f}")

print("\n" + "=" * 60)
print("ДИАГНОСТИКА ЗАВЕРШЕНА")
print("=" * 60)
