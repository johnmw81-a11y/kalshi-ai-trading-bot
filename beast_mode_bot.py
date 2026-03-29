import os
import requests
import time
import uuid
import datetime
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

TARGET_TICKER = "KXSENATETXR-26-KP"
MAX_POSITION_DOLLARS = 45   
TRADE_AMOUNT_DOLLARS = 20   
BUY_PRICE_LIMIT = 75        
HARVEST_PRICE = 85          

def sign_request(private_key_str, timestamp, method, path):
    private_key = serialization.load_pem_private_key(
        private_key_str.encode('utf-8'), 
        password=None
    )
    msg_string = timestamp + method + path
    signature = private_key.sign(
        msg_string.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

def make_kalshi_request(method, path, payload=None):
    api_key_id = os.getenv('KALSHI_KEY_ID')
    private_key_str = os.getenv('KALSHI_PRIVATE_KEY')
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    signature = sign_request(private_key_str, timestamp, method, "/trade-api/v2" + path)
    
    headers = {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }
    
    url = f"{base_url}{path}"
    if method == "GET":
        return requests.get(url, headers=headers)
    elif method == "POST":
        return requests.post(url, json=payload, headers=headers)

def run_sniper():
    print(f"🤖 X-RAY HARVESTER WAKING UP: {time.strftime('%X')} CT")
    
    if not os.getenv('KALSHI_KEY_ID') or not os.getenv('KALSHI_PRIVATE_KEY'):
        print("❌ Missing Secrets!")
        return

    # 1. READ THE LIVE MARKET (X-RAY MODE)
    print(f"📊 Checking live prices for {TARGET_TICKER}...")
    market_resp = make_kalshi_request("GET", f"/markets/{TARGET_TICKER}")
    
    # 🚨 X-RAY: PRINT THE RAW MARKET DATA 🚨
    print(f"RAW MARKET JSON: {market_resp.text}")
    
    market_data = market_resp.json().get('market', {})
    yes_ask = market_data.get('yes_ask', 100) 
    yes_bid = market_data.get('yes_bid', 0)   
    print(f"📈 Live Market -> Buy at: {yes_ask}¢ | Sell at: {yes_bid}¢")

    # 2. CHECK YOUR POCKETS (X-RAY MODE)
    print("💼 Checking your Kalshi portfolio...")
    pos_resp = make_kalshi_request("GET", "/portfolio/positions")
    
    # 🚨 X-RAY: PRINT THE RAW PORTFOLIO DATA 🚨
    print(f"RAW PORTFOLIO JSON: {pos_resp.text}")
    
    current_contracts = 0
    if pos_resp.status_code == 200:
        positions = pos_resp.json().get('market_positions', [])
        for p in positions:
            if p.get('ticker') == TARGET_TICKER:
                current_contracts = p.get('position', 0)
    
    current_value_dollars = (current_contracts * yes_bid) / 100
    print(f"💰 You currently own {current_contracts} contracts")
    print("⏸️ Pausing here to read the X-Ray data.")

if __name__ == "__main__":
    run_sniper()
