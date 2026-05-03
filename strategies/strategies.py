# strategies.py - Расширенные стратегии для бота
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import numpy as np
from typing import List, Dict, Optional, Tuple

class AdvancedStrategies:
    """Расширенные торговые стратегии"""
    
    def __init__(self):
        self.name = "Advanced Strategies"
    
    def rsi_strategy(self, prices: List[float], period: int = 14, oversold: int = 30, overbought: int = 70) -> Optional[str]:
        """RSI стратегия (индекс относительной силы)"""
        if len(prices) < period + 1:
            return None
        
        # Вычисляем изменения цен
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Разделяем на положительные и отрицательные
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        # Вычисляем средние
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        if rsi < oversold:
            return "buy"
        elif rsi > overbought:
            return "sell"
        return None
    
    def macd_strategy(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[str]:
        """MACD стратегия (схождение/расхождение скользящих средних)"""
        if len(prices) < slow + signal:
            return None
        
        # Вычисляем EMA
        def ema(data, period):
            multiplier = 2 / (period + 1)
            ema_values = [data[0]]
            for price in data[1:]:
                ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
            return ema_values
        
        fast_ema = ema(prices, fast)
        slow_ema = ema(prices, slow)
        
        macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
        signal_line = ema(macd_line, signal)
        
        if len(macd_line) < 2 or len(signal_line) < 2:
            return None
        
        if macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]:
            return "buy"
        elif macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]:
            return "sell"
        
        return None
    
    def bollinger_bands_strategy(self, prices: List[float], period: int = 20, std_dev: float = 2) -> Optional[str]:
        """Стратегия полос Боллинджера"""
        if len(prices) < period:
            return None
        
        # Средняя цена
        sma = sum(prices[-period:]) / period
        
        # Стандартное отклонение
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        
        upper_band = sma + std_dev * std
        lower_band = sma - std_dev * std
        
        current_price = prices[-1]
        
        if current_price <= lower_band:
            return "buy"
        elif current_price >= upper_band:
            return "sell"
        
        return None
    
    def volume_strategy(self, prices: List[float], volumes: List[float], period: int = 20) -> Optional[str]:
        """Объёмная стратегия"""
        if len(prices) < period or len(volumes) < period:
            return None
        
        avg_volume = sum(volumes[-period:]) / period
        current_volume = volumes[-1]
        price_change = (prices[-1] - prices[-2]) / prices[-2] if len(prices) > 1 else 0
        
        if current_volume > avg_volume * 1.5 and price_change > 0.01:
            return "buy"
        elif current_volume > avg_volume * 1.5 and price_change < -0.01:
            return "sell"
        
        return None
    
    def ichimoku_strategy(self, prices: List[float]) -> Optional[str]:
        """Стратегия Ишимоку"""
        if len(prices) < 52:
            return None
        
        # Tenkan-sen (быстрая линия)
        tenkan_period = 9
        tenkan = (max(prices[-tenkan_period:]) + min(prices[-tenkan_period:])) / 2
        
        # Kijun-sen (медленная линия)
        kijun_period = 26
        kijun = (max(prices[-kijun_period:]) + min(prices[-kijun_period:])) / 2
        
        current_price = prices[-1]
        
        if current_price > tenkan and current_price > kijun and tenkan > kijun:
            return "buy"
        elif current_price < tenkan and current_price < kijun and tenkan < kijun:
            return "sell"
        
        return None
    
    def machine_learning_strategy(self, prices: List[float]) -> Optional[str]:
        """Простая ML-стратегия (логистическая регрессия)"""
        if len(prices) < 50:
            return None
        
        # Простое предсказание тренда
        short_ma = sum(prices[-10:]) / 10
        long_ma = sum(prices[-30:]) / 30
        
        if short_ma > long_ma * 1.01:
            return "buy"
        elif short_ma < long_ma * 0.99:
            return "sell"
        
        return None

# Создаём экземпляр для импорта
advanced_strategies = AdvancedStrategies()
