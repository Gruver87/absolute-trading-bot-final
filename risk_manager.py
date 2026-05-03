# -*- coding: utf-8 -*-
# risk_manager.py - РњРѕРґСѓР»СЊ Р·Р°С‰РёС‚С‹ РєР°РїРёС‚Р°Р»Р°
# рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

import time
from datetime import datetime, date
from typing import Dict, List, Optional

class RiskManager:
    """РЈРїСЂР°РІР»РµРЅРёРµ СЂРёСЃРєР°РјРё Рё Р·Р°С‰РёС‚Р° РєР°РїРёС‚Р°Р»Р°"""
    
    def __init__(self, initial_balance: float = 0):
        self.initial_balance = initial_balance
        self.daily_start_balance = initial_balance
        self.last_reset_date = date.today()
        self.max_daily_loss_pct = 5.0  # 5% РјР°РєСЃРёРјР°Р»СЊРЅР°СЏ РїСЂРѕСЃР°РґРєР° РІ РґРµРЅСЊ
        self.max_drawdown_pct = 15.0   # 15% РјР°РєСЃРёРјР°Р»СЊРЅР°СЏ РѕР±С‰Р°СЏ РїСЂРѕСЃР°РґРєР°
        self.is_protection_active = True
        self.trades_today = 0
        self.alerts = []
        
    def check_daily_reset(self):
        """РЎР±СЂРѕСЃ РґРЅРµРІРЅРѕР№ СЃС‚Р°С‚РёСЃС‚РёРєРё"""
        today = date.today()
        if today != self.last_reset_date:
            self.daily_start_balance = self.initial_balance
            self.trades_today = 0
            self.last_reset_date = today
            self.add_alert("рџ“… Р”РЅРµРІРЅР°СЏ СЃС‚Р°С‚РёСЃС‚РёРєР° СЃР±СЂРѕС€РµРЅР°", "info")
            return True
        return False
    
    def update_balance(self, current_balance: float):
        """РћР±РЅРѕРІРёС‚СЊ С‚РµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ"""
        self.initial_balance = current_balance
        self.check_daily_reset()
    
    def check_daily_loss(self, current_balance: float) -> Dict:
        """РџСЂРѕРІРµСЂРёС‚СЊ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РїСЂРѕСЃР°РґРєРё"""
        self.check_daily_reset()
        
        daily_loss_pct = (self.daily_start_balance - current_balance) / self.daily_start_balance * 100
        
        if daily_loss_pct >= self.max_daily_loss_pct and self.is_protection_active:
            return {
                "protected": True,
                "reason": f"Р”РЅРµРІРЅР°СЏ РїСЂРѕСЃР°РґРєР° {daily_loss_pct:.1f}% РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚ {self.max_daily_loss_pct}%",
                "action": "STOP_ALL",
                "severity": "critical"
            }
        
        return {"protected": False}
    
    def check_total_drawdown(self, current_balance: float, peak_balance: float) -> Dict:
        """РџСЂРѕРІРµСЂРёС‚СЊ РѕР±С‰СѓСЋ РїСЂРѕСЃР°РґРєСѓ РѕС‚ РїРёРєР°"""
        if peak_balance <= 0:
            return {"protected": False}
        
        drawdown_pct = (peak_balance - current_balance) / peak_balance * 100
        
        if drawdown_pct >= self.max_drawdown_pct and self.is_protection_active:
            return {
                "protected": True,
                "reason": f"РћР±С‰Р°СЏ РїСЂРѕСЃР°РґРєР° {drawdown_pct:.1f}% РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚ {self.max_drawdown_pct}%",
                "action": "EMERGENCY_STOP",
                "severity": "critical"
            }
        
        return {"protected": False}
    
    def check_trade_size(self, balance: float, trade_amount: float) -> Dict:
        """РџСЂРѕРІРµСЂРёС‚СЊ СЂР°Р·РјРµСЂ СЃРґРµР»РєРё"""
        position_size_pct = trade_amount / balance * 100 if balance > 0 else 100
        
        if position_size_pct > 20:
            return {
                "allowed": False,
                "reason": f"Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё {position_size_pct:.1f}% РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚ 20%",
                "suggested": balance * 0.1
            }
        
        return {"allowed": True}
    
    def add_alert(self, message: str, level: str = "warning"):
        """Р”РѕР±Р°РІРёС‚СЊ Р°Р»РµСЂС‚"""
        self.alerts.insert(0, {
            "timestamp": time.time(),
            "message": message,
            "level": level
        })
        if len(self.alerts) > 20:
            self.alerts.pop()
    
    def get_alerts(self) -> List[Dict]:
        """РџРѕР»СѓС‡РёС‚СЊ РїРѕСЃР»РµРґРЅРёРµ Р°Р»РµСЂС‚С‹"""
        return self.alerts[:10]
    
    def get_stats(self) -> Dict:
        """РџРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚РёСЃС‚РёРєСѓ СЂРёСЃРє-РјРµРЅРµРґР¶РјРµРЅС‚Р°"""
        return {
            "daily_loss_limit": self.max_daily_loss_pct,
            "drawdown_limit": self.max_drawdown_pct,
            "protection_active": self.is_protection_active,
            "daily_start_balance": self.daily_start_balance,
            "trades_today": self.trades_today,
            "alerts": self.get_alerts()
        }