# -*- coding: utf-8 -*-
# futures_trading.py - Торговля фьючерсами
# ?? DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import os
import time
import requests
import hashlib
import hmac
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

class FuturesTrading:
    """Торговля фьючерсами на MEXC"""
    
    def __init__(self):
        self.api_key = os.getenv("MEXC_API_KEY")
        self.api_secret = os.getenv("MEXC_API_SECRET")
        self.base_url = "https://api.mexc.com"
        self.leverage = 5  # Плечо по умолчанию 5x
        self.positions = []
        
        print("? Модуль фьючерсов инициализирован")
    
    def _generate_signature(self, params: str) -> str:
        return hmac.new(self.api_secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    
    def set_leverage(self, symbol: str = "BTCUSDT", leverage: int = 5) -> Dict:
        """Установить кредитное плечо"""
        try:
            timestamp = int(time.time() * 1000)
            params = f"symbol={symbol}&leverage={leverage}&timestamp={timestamp}"
            signature = self._generate_signature(params)
            headers = {"X-MEXC-APIKEY": self.api_key}
            
            response = requests.post(f"{self.base_url}/api/v3/leverage?{params}&signature={signature}", 
                                     headers=headers, timeout=10)
            if response.status_code == 200:
                self.leverage = leverage
                return {"success": True, "leverage": leverage}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def open_long(self, symbol: str = "BTCUSDT", amount_usdt: float = 100, leverage: int = None) -> Dict:
        """Открыть длинную позицию (лонг)"""
        lev = leverage or self.leverage
        try:
            timestamp = int(time.time() * 1000)
            quantity = amount_usdt * lev / self._get_price(symbol)
            
            params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
            signature = self._generate_signature(params)
            headers = {"X-MEXC-APIKEY": self.api_key}
            
            response = requests.post(f"{self.base_url}/api/v3/order?{params}&signature={signature}", 
                                     headers=headers, timeout=10)
            
            if response.status_code == 200:
                order = response.json()
                self.positions.append({
                    "type": "long",
                    "symbol": symbol,
                    "price": self._get_price(symbol),
                    "amount_usdt": amount_usdt,
                    "leverage": lev,
                    "entry_time": time.time()
                })
                return {"success": True, "order": order, "message": f"? Открыта LONG позиция {amount_usdt} USDT с плечом {lev}x"}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def open_short(self, symbol: str = "BTCUSDT", amount_usdt: float = 100, leverage: int = None) -> Dict:
        """Открыть короткую позицию (шорт)"""
        lev = leverage or self.leverage
        try:
            timestamp = int(time.time() * 1000)
            quantity = amount_usdt * lev / self._get_price(symbol)
            
            params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
            signature = self._generate_signature(params)
            headers = {"X-MEXC-APIKEY": self.api_key}
            
            response = requests.post(f"{self.base_url}/api/v3/order?{params}&signature={signature}", 
                                     headers=headers, timeout=10)
            
            if response.status_code == 200:
                order = response.json()
                self.positions.append({
                    "type": "short",
                    "symbol": symbol,
                    "price": self._get_price(symbol),
                    "amount_usdt": amount_usdt,
                    "leverage": lev,
                    "entry_time": time.time()
                })
                return {"success": True, "order": order, "message": f"? Открыта SHORT позиция {amount_usdt} USDT с плечом {lev}x"}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def close_position(self, position_index: int) -> Dict:
        """Закрыть позицию по индексу"""
        if position_index >= len(self.positions):
            return {"success": False, "error": "Позиция не найдена"}
        
        pos = self.positions[position_index]
        current_price = self._get_price(pos["symbol"])
        
        if pos["type"] == "long":
            profit_pct = (current_price - pos["price"]) / pos["price"] * 100 * pos["leverage"]
        else:
            profit_pct = (pos["price"] - current_price) / pos["price"] * 100 * pos["leverage"]
        
        profit_usdt = pos["amount_usdt"] * profit_pct / 100
        
        self.positions.pop(position_index)
        
        return {
            "success": True,
            "profit_pct": profit_pct,
            "profit_usdt": profit_usdt,
            "message": f"?? Позиция закрыта. Прибыль: {profit_pct:.2f}% (${profit_usdt:.2f})"
        }
    
    def _get_price(self, symbol: str = "BTCUSDT") -> float:
        """Получить текущую цену"""
        try:
            response = requests.get(f"{self.base_url}/api/v3/ticker/price?symbol={symbol}", timeout=5)
            if response.status_code == 200:
                return float(response.json().get("price", 0))
            return 0.0
        except:
            return 0.0
    
    def get_positions(self) -> List[Dict]:
        """Получить список открытых позиций"""
        current_price = self._get_price()
        positions_info = []
        
        for i, pos in enumerate(self.positions):
            if pos["type"] == "long":
                profit_pct = (current_price - pos["price"]) / pos["price"] * 100 * pos["leverage"]
            else:
                profit_pct = (pos["price"] - current_price) / pos["price"] * 100 * pos["leverage"]
            
            positions_info.append({
                "index": i,
                "type": pos["type"],
                "entry_price": pos["price"],
                "current_price": current_price,
                "profit_pct": profit_pct,
                "profit_usdt": pos["amount_usdt"] * profit_pct / 100,
                "leverage": pos["leverage"],
                "amount_usdt": pos["amount_usdt"]
            })
        
        return positions_info
    
    def get_stats(self) -> Dict:
        return {
            "leverage": self.leverage,
            "open_positions": len(self.positions),
            "positions": self.get_positions()
        }
