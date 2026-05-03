# -*- coding: utf-8 -*-
# social_signals.py - Социальные сигналы
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import os
import time
import requests
import random
import re
from typing import Dict, List, Optional

class SocialSignals:
    """Анализ соцсетей и новостей"""
    
    def __init__(self):
        self.signals = []
        self.keywords = {
            "bullish": ["покупаю", "buy", "long", "бычий", "ракета", "луна", "moon", "rocket"],
            "bearish": ["продаю", "sell", "short", "медвежий", "падение", "dump", "crash"]
        }
        
        self.influencers = [
            "elonmusk", "cz_binance", "VitalikButerin", "crypto", "CoinDesk"
        ]
        
    def analyze_tweet(self, tweet_text: str) -> Optional[str]:
        """Анализ твита на сентимент"""
        tweet_lower = tweet_text.lower()
        
        bullish_score = sum(1 for word in self.keywords["bullish"] if word in tweet_lower)
        bearish_score = sum(1 for word in self.keywords["bearish"] if word in tweet_lower)
        
        if bullish_score > bearish_score:
            return "bullish"
        elif bearish_score > bullish_score:
            return "bearish"
        return None
    
    def get_kol_signals(self) -> List[Dict]:
        """Получить сигналы от ключевых фигур (симуляция)"""
        # В реальности здесь API Twitter/X
        simulated_signals = [
            {"source": "Elon Musk", "signal": "bullish", "confidence": 85},
            {"source": "CZ", "signal": "bullish", "confidence": 70},
            {"source": "CoinDesk", "signal": "bearish", "confidence": 60}
        ]
        return simulated_signals
    
    def get_news_sentiment(self) -> Dict:
        """Анализ новостей (симуляция)"""
        return {
            "overall": "neutral",
            "positive_articles": 3,
            "negative_articles": 2,
            "top_headline": "Bitcoin ETF inflows surge",
            "timestamp": time.time()
        }
    
    def get_whale_alerts(self) -> List[Dict]:
        """Отслеживание китов (симуляция)"""
        return [
            {"amount": 1000, "asset": "BTC", "exchange": "Binance", "type": "buy"},
            {"amount": 500, "asset": "ETH", "exchange": "Coinbase", "type": "sell"}
        ]
    
    def get_combined_signal(self) -> Dict:
        """Комбинированный сигнал из всех источников"""
        kol_signals = self.get_kol_signals()
        news = self.get_news_sentiment()
        whales = self.get_whale_alerts()
        
        bullish_count = sum(1 for s in kol_signals if s["signal"] == "bullish")
        bearish_count = sum(1 for s in kol_signals if s["signal"] == "bearish")
        
        whale_buy = sum(1 for w in whales if w["type"] == "buy")
        whale_sell = sum(1 for w in whales if w["type"] == "sell")
        
        signal = "neutral"
        confidence = 50
        
        if bullish_count > bearish_count and whale_buy > whale_sell:
            signal = "bullish"
            confidence = 70
        elif bearish_count > bullish_count and whale_sell > whale_buy:
            signal = "bearish"
            confidence = 70
        
        return {
            "signal": signal,
            "confidence": confidence,
            "kol_signals": kol_signals,
            "news": news,
            "whale_alerts": whales,
            "timestamp": time.time()
        }
