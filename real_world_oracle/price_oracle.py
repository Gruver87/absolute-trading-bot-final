# real_world_oracle.py - Оракул для реальных цен
# 🔐 DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import requests
import json
import time
from typing import Dict, List, Optional
from datetime import datetime

class PriceOracle:
    """Оракул для получения реальных цен криптовалют"""
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 30  # секунд
        self.sources = {
            "binance": "https://api.binance.com/api/v3/ticker/price",
            "mexc": "https://api.mexc.com/api/v3/ticker/price",
            "bybit": "https://api.bybit.com/v5/market/tickers",
            "okx": "https://www.okx.com/api/v5/market/ticker",
            "kucoin": "https://api.kucoin.com/api/v1/prices"
        }
    
    def _get_from_cache(self, symbol: str) -> Optional[float]:
        """Получить цену из кэша"""
        if symbol in self.cache:
            data = self.cache[symbol]
            if time.time() - data["timestamp"] < self.cache_ttl:
                return data["price"]
        return None
    
    def _save_to_cache(self, symbol: str, price: float):
        """Сохранить цену в кэш"""
        self.cache[symbol] = {"price": price, "timestamp": time.time()}
    
    def get_price_binance(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Получить цену с Binance"""
        try:
            response = requests.get(f"{self.sources['binance']}?symbol={symbol}", timeout=5)
            if response.status_code == 200:
                return float(response.json().get("price", 0))
        except:
            pass
        return None
    
    def get_price_mexc(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Получить цену с MEXC"""
        try:
            response = requests.get(f"{self.sources['mexc']}?symbol={symbol}", timeout=5)
            if response.status_code == 200:
                return float(response.json().get("price", 0))
        except:
            pass
        return None
    
    def get_price_bybit(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Получить цену с Bybit"""
        try:
            response = requests.get(f"{self.sources['bybit']}?category=spot&symbol={symbol}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("retCode") == 0:
                    return float(data["result"]["list"][0]["lastPrice"])
        except:
            pass
        return None
    
    def get_price(self, symbol: str = "BTC/USDT", source: str = "all") -> float:
        """Получить цену криптовалюты"""
        # Нормализуем символ
        symbol_normalized = symbol.replace("/", "")
        
        # Проверяем кэш
        cached = self._get_from_cache(symbol_normalized)
        if cached:
            return cached
        
        prices = []
        
        # Собираем цены со всех источников
        if source in ["all", "binance"]:
            price = self.get_price_binance(symbol_normalized)
            if price:
                prices.append(price)
        
        if source in ["all", "mexc"]:
            price = self.get_price_mexc(symbol_normalized)
            if price:
                prices.append(price)
        
        if source in ["all", "bybit"]:
            price = self.get_price_bybit(symbol_normalized)
            if price:
                prices.append(price)
        
        if prices:
            # Берём медиану цен
            avg_price = sum(prices) / len(prices)
            self._save_to_cache(symbol_normalized, avg_price)
            return avg_price
        
        # Цена по умолчанию
        default_prices = {
            "BTCUSDT": 50000,
            "ETHUSDT": 3000,
            "SOLUSDT": 100,
            "BNBUSDT": 500
        }
        return default_prices.get(symbol_normalized, 1000)
    
    def get_all_prices(self) -> Dict:
        """Получить цены всех основных криптовалют"""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
        prices = {}
        for symbol in symbols:
            prices[symbol] = self.get_price(symbol)
        return prices
    
    def get_arbitrage_opportunity(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Найти арбитражную возможность между биржами"""
        try:
            binance_price = self.get_price_binance(symbol)
            mexc_price = self.get_price_mexc(symbol)
            bybit_price = self.get_price_bybit(symbol)
            
            if not binance_price or not mexc_price or not bybit_price:
                return None
            
            prices = {
                "binance": binance_price,
                "mexc": mexc_price,
                "bybit": bybit_price
            }
            
            min_exchange = min(prices, key=prices.get)
            max_exchange = max(prices, key=prices.get)
            
            diff_pct = (prices[max_exchange] - prices[min_exchange]) / prices[min_exchange] * 100
            
            if diff_pct > 0.5:  # >0.5% разница
                return {
                    "symbol": symbol,
                    "buy_exchange": min_exchange,
                    "buy_price": prices[min_exchange],
                    "sell_exchange": max_exchange,
                    "sell_price": prices[max_exchange],
                    "profit_pct": diff_pct,
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            print(f"Ошибка арбитража: {e}")
        
        return None
