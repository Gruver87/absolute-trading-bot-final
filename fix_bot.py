# -*- coding: utf-8 -*-
# fix_bot.py - Быстрое исправление для тестового режима
import random
import time

print("?? ТЕСТОВЫЙ РЕЖИМ БОТА")
print("=" * 50)

balance = 10000
print(f"?? Начальный баланс: ${balance}")

count = 0
while True:
    count += 1
    # Симулируем цену BTC
    price = 78000 + random.randint(-500, 500)
    
    # Симулируем сигнал нейросети
    signals = ["BUY", "SELL", "HOLD"]
    weights = [0.3, 0.3, 0.4]
    signal = random.choices(signals, weights=weights)[0]
    confidence = random.randint(55, 95)
    
    print(f"?? #{count} | BTC: ${price} | Сигнал: {signal} ({confidence}%) | Баланс: ${balance:.2f}")
    
    time.sleep(3)