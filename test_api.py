# -*- coding: utf-8 -*-
import os
import requests
import hashlib
import hmac
import time
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("MEXC_API_KEY")
SECRET_KEY = os.getenv("MEXC_API_SECRET")

print(f"?? API Key: {API_KEY[:15]}...")
print(f"?? Secret Key: {SECRET_KEY[:15]}...")

url = "https://api.mexc.com/api/v3/account"
timestamp = int(time.time() * 1000)
params = f"timestamp={timestamp}"
signature = hmac.new(SECRET_KEY.encode(), params.encode(), hashlib.sha256).hexdigest()
headers = {"X-MEXC-APIKEY": API_KEY}

try:
    response = requests.get(f"{url}?{params}&signature={signature}", headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        print("? API КЛЮЧИ РАБОТАЮТ!")
        for b in data.get("balances", []):
            if float(b.get("free", 0)) > 0:
                print(f"   ?? {b['asset']}: {b['free']}")
    else:
        print(f"? Ошибка: {response.status_code}")
except Exception as e:
    print(f"? Ошибка: {e}")
