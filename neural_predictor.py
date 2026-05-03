# -*- coding: utf-8 -*-
# neural_predictor.py - Нейросетевая модель для предсказания цен
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import numpy as np
import json
import os
import time
from typing import List, Dict, Tuple, Optional

class NeuralPredictor:
    """Нейросетевая модель для предсказания цен криптовалют"""
    
    def __init__(self, input_size: int = 60, hidden_size: int = 128):
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = 3  # up, down, stay
        
        # Инициализация весов нейросети (ИСПРАВЛЕНО)
        self.weights_input_hidden = np.random.randn(self.input_size, self.hidden_size) * 0.1
        self.weights_hidden_output = np.random.randn(self.hidden_size, self.output_size) * 0.1
        self.bias_hidden = np.zeros(self.hidden_size)
        self.bias_output = np.zeros(self.output_size)
        
        self.training_data = []
        self.accuracy = 0.0
        self.last_prediction = None
        
        # Загрузка сохранённой модели если есть
        self._load_model()
        
        print("? Нейросетевая модель инициализирована")
    
    def _sigmoid(self, x: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))
    
    def _relu(self, x: np.ndarray) -> np.ndarray:
        return np.maximum(0, x)
    
    def _softmax(self, x: np.ndarray) -> np.ndarray:
        exp_x = np.exp(x - np.max(x))
        return exp_x / np.sum(exp_x)
    
    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Прямой проход по сети"""
        hidden = self._relu(np.dot(x, self.weights_input_hidden) + self.bias_hidden)
        output = self._softmax(np.dot(hidden, self.weights_hidden_output) + self.bias_output)
        return hidden, output
    
    def predict(self, prices: List[float]) -> Dict:
        """Предсказать движение цены"""
        if len(prices) < self.input_size:
            return {"prediction": "hold", "confidence": 50, "reasons": ["Недостаточно данных"]}
        
        # Нормализация данных
        recent_prices = prices[-self.input_size:]
        normalized = (recent_prices - np.mean(recent_prices)) / (np.std(recent_prices) + 1e-8)
        
        # Прогон через нейросеть
        _, output = self.forward(normalized)
        
        # Интерпретация результата
        predictions = ["up", "down", "hold"]
        idx = np.argmax(output)
        confidence = float(output[idx] * 100)
        prediction = predictions[idx]
        
        self.last_prediction = {
            "prediction": prediction,
            "confidence": confidence,
            "timestamp": time.time(),
            "price": prices[-1],
            "up_probability": float(output[0]),
            "down_probability": float(output[1]),
            "hold_probability": float(output[2])
        }
        
        # Добавляем причины для Explainable AI
        reasons = self._generate_reasons(prices, prediction, confidence)
        
        return {
            "prediction": prediction,
            "confidence": confidence,
            "reasons": reasons,
            "probabilities": {
                "up": float(output[0]),
                "down": float(output[1]),
                "hold": float(output[2])
            }
        }
    
    def _generate_reasons(self, prices: List[float], prediction: str, confidence: float) -> List[str]:
        """Генерация объяснений для предсказания"""
        reasons = []
        
        if len(prices) >= 20:
            momentum = (prices[-1] - prices[-20]) / prices[-20] * 100
            if prediction == "up" and momentum > 0:
                reasons.append(f"Моментум роста {momentum:.1f}% за 20 периодов")
            elif prediction == "down" and momentum < 0:
                reasons.append(f"Моментум падения {abs(momentum):.1f}% за 20 периодов")
        
        if len(prices) >= 50:
            support = min(prices[-50:])
            resistance = max(prices[-50:])
            current = prices[-1]
            if prediction == "up" and current <= support * 1.02:
                reasons.append(f"Цена у уровня поддержки (${support:.0f})")
            elif prediction == "down" and current >= resistance * 0.98:
                reasons.append(f"Цена у уровня сопротивления (${resistance:.0f})")
        
        if not reasons:
            reasons.append(f"Нейросеть предсказывает {prediction} с уверенностью {confidence:.0f}%")
        
        return reasons
    
    def train(self, historical_data: List[Dict], epochs: int = 10) -> None:
        """Обучение нейросети на исторических данных"""
        print(f"?? Начало обучения нейросети на {len(historical_data)} примерах...")
        
        learning_rate = 0.01
        for epoch in range(epochs):
            total_loss = 0
            correct = 0
            
            for data in historical_data:
                prices = data.get("prices", [])
                actual = data.get("actual", "hold")
                
                if len(prices) < self.input_size:
                    continue
                
                # Подготовка данных
                normalized = (prices[-self.input_size:] - np.mean(prices[-self.input_size:])) / (np.std(prices[-self.input_size:]) + 1e-8)
                
                # Целевая переменная
                target = [1 if actual == "up" else 0, 1 if actual == "down" else 0, 1 if actual == "hold" else 0]
                
                # Forward pass
                hidden, output = self.forward(normalized)
                
                # Backward pass
                output_error = output - target
                hidden_error = np.dot(output_error, self.weights_hidden_output.T) * (hidden > 0)
                
                # Обновление весов
                self.weights_hidden_output -= learning_rate * np.outer(hidden, output_error)
                self.weights_input_hidden -= learning_rate * np.outer(normalized, hidden_error)
                self.bias_hidden -= learning_rate * hidden_error
                self.bias_output -= learning_rate * output_error
                
                # Подсчёт точности
                if np.argmax(output) == np.argmax(target):
                    correct += 1
                
                total_loss += np.sum(output_error ** 2)
            
            accuracy = correct / max(len(historical_data), 1) * 100
            print(f"   Эпоха {epoch + 1}/{epochs}: Потери = {total_loss:.4f}, Точность = {accuracy:.1f}%")
            self.accuracy = accuracy
        
        self._save_model()
        print(f"? Обучение завершено! Точность модели: {self.accuracy:.1f}%")
    
    def _save_model(self) -> None:
        """Сохранение модели в файл"""
        model_data = {
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "output_size": self.output_size,
            "weights_input_hidden": self.weights_input_hidden.tolist(),
            "weights_hidden_output": self.weights_hidden_output.tolist(),
            "bias_hidden": self.bias_hidden.tolist(),
            "bias_output": self.bias_output.tolist(),
            "accuracy": self.accuracy
        }
        with open("neural_model.json", "w") as f:
            json.dump(model_data, f)
    
    def _load_model(self) -> None:
        """Загрузка модели из файла"""
        if os.path.exists("neural_model.json"):
            try:
                with open("neural_model.json", "r") as f:
                    model_data = json.load(f)
                self.weights_input_hidden = np.array(model_data["weights_input_hidden"])
                self.weights_hidden_output = np.array(model_data["weights_hidden_output"])
                self.bias_hidden = np.array(model_data["bias_hidden"])
                self.bias_output = np.array(model_data["bias_output"])
                self.accuracy = model_data.get("accuracy", 0)
                print(f"? Модель загружена! Точность: {self.accuracy:.1f}%")
            except:
                print("?? Не удалось загрузить модель, создана новая")
    
    def get_stats(self) -> Dict:
        return {
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "output_size": self.output_size,
            "accuracy": self.accuracy,
            "last_prediction": self.last_prediction,
            "model_loaded": os.path.exists("neural_model.json")
        }
