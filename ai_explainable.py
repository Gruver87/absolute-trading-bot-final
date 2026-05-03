# -*- coding: utf-8 -*-
# ai_explainable.py - Обновлённый AI с нейросетью
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import os
import time
from typing import Dict, List, Optional
from neural_predictor import NeuralPredictor

class ExplainableAI:
    """AI с нейросетевыми предсказаниями и объяснениями"""
    
    def __init__(self):
        self.decision_log = []
        self.risk_level = int(os.getenv("AI_RISK_LEVEL", "5")) if os.getenv("AI_RISK_LEVEL") else 5
        self.explain_mode = True
        self.neural_network = NeuralPredictor()
        print("? Explainable AI с нейросетью инициализирован")
    
    def predict_with_neural_network(self, prices: List[float]) -> Dict:
        """Предсказание с помощью нейросети"""
        return self.neural_network.predict(prices)
    
    def analyze_with_explanation(self, prices: List[float], volumes: List[float] = None) -> Dict:
        if len(prices) < 20:
            return {"signal": None, "reasons": ["Недостаточно данных для анализа"]}
        
        reasons = []
        signal = None
        
        # 1. Нейросетевое предсказание (приоритет)
        neural_pred = self.neural_network.predict(prices)
        if neural_pred["confidence"] > 65:
            if neural_pred["prediction"] == "up":
                signal = "buy"
                reasons.append(f"?? Нейросеть: {neural_pred['reasons'][0]} (уверенность {neural_pred['confidence']:.0f}%)")
            elif neural_pred["prediction"] == "down":
                signal = "sell"
                reasons.append(f"?? Нейросеть: {neural_pred['reasons'][0]} (уверенность {neural_pred['confidence']:.0f}%)")
        
        # 2. Моментум анализ
        momentum = (prices[-1] - prices[-20]) / prices[-20] * 100
        if momentum > 0.5 and not signal:
            signal = "buy"
            reasons.append(f"Положительный моментум: +{momentum:.1f}% за 20 периодов")
        elif momentum < -0.5 and not signal:
            signal = "sell"
            reasons.append(f"Отрицательный моментум: {momentum:.1f}% за 20 периодов")
        
        # 3. Анализ тренда
        if len(prices) >= 30:
            short_ma = sum(prices[-10:]) / 10
            long_ma = sum(prices[-30:]) / 30
            if short_ma > long_ma * 1.005 and not signal:
                signal = "buy"
                reasons.append(f"Бычий тренд: MA10 ({short_ma:.0f}) > MA30 ({long_ma:.0f})")
            elif short_ma < long_ma * 0.995 and not signal:
                signal = "sell"
                reasons.append(f"Медвежий тренд: MA10 ({short_ma:.0f}) < MA30 ({long_ma:.0f})")
        
        # 4. Уровни поддержки/сопротивления
        if len(prices) >= 50:
            support = min(prices[-50:])
            resistance = max(prices[-50:])
            current = prices[-1]
            if current <= support * 1.01 and not signal:
                signal = "buy"
                reasons.append(f"Цена у уровня поддержки (${support:.0f})")
            elif current >= resistance * 0.99 and not signal:
                signal = "sell"
                reasons.append(f"Цена у уровня сопротивления (${resistance:.0f})")
        
        if not reasons:
            reasons = ["Рынок стабилен, сигналов нет"]
        
        self.decision_log.append({
            "timestamp": time.time(),
            "signal": signal,
            "price": prices[-1],
            "reasons": reasons,
            "risk_level": self.risk_level,
            "neural_confidence": neural_pred.get("confidence", 0)
        })
        
        return {"signal": signal, "reasons": reasons[:5]}
    
    def explain_decision(self, signal: str, price: float, reasons: List[str]) -> str:
        if not reasons:
            reasons = ["Анализ рынка"]
        
        explanation = f"""
?? РЕШЕНИЕ: {signal.upper()} по цене ${price:.2f}

?? ПРИЧИНЫ:
{chr(10).join([f'   • {r}' for r in reasons[:5]])}

?? РИСК-МЕНЕДЖМЕНТ:
   • Стоп-лосс: -5%
   • Тейк-профит: +10%
   • Уровень риска: {self.risk_level}/10

? Вопросы? Напишите 'почему' для деталей
"""
        return explanation.strip()
    
    def train_neural_network(self, historical_data: List[Dict], epochs: int = 10):
        """Обучение нейросети на исторических данных"""
        self.neural_network.train(historical_data, epochs)
    
    def get_stats(self) -> Dict:
        neural_stats = self.neural_network.get_stats()
        return {
            "total_decisions": len(self.decision_log),
            "risk_level": self.risk_level,
            "explain_mode": self.explain_mode,
            "latest_decision": self.decision_log[-1] if self.decision_log else None,
            "neural_network": neural_stats
        }
