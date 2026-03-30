import os
import requests
import time
import uuid
import datetime
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# --- POLITICS CONFIG ---
TARGET_TICKER = "KXSENATETXR-26-KP" 
MAX_POSITION_DOLLARS = 45   
TRADE_AMOUNT_DOLLARS = 20   

# --- THE PRO SHIELDS ---
BUY_PRICE_LIMIT = 65        
HARVEST_PRICE = 85          
STOP_LOSS_PRICE = 35        

def sign_request(private_key_str, timestamp, method, path):
    private_key = serialization.load_pem_private_key(private_key_str.encode('utf-8'), password=None)
    msg_string = timestamp + method + path
    signature = private_key.sign(msg_string.encode('utf-8'), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return base64.b64encode(signature).decode('utf-8')

def make_kalshi_request(method, path, payload=None):
    api_key_id = os.getenv('KALSHI_KEY_ID')
    private_key_str = os.getenv('KALSHI_PRIVATE_KEY')
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    signature = sign_request(private_key_str, timestamp, method, "/trade-api/v2" + path)
    headers = {"KALSHI-ACCESS-KEY": api_key_id, "KALSHI-ACCESS-SIGNATURE": signature, "KALSHI-ACCESS-TIMESTAMP": timestamp, "Content-Type": "application/json"}
    url = f"{base_url}{path}"
    if method == "GET": return requests.get(url, headers=headers)
    elif method == "POST": return requests.post(url, json=payload, headers=headers)

def run_politics_sniper():
    print(f"🤖 SMART HARVESTER WAKING UP: {time.strftime('%X')} CT")
    if not os.getenv('KALSHI_KEY_ID') or not os.getenv('KALSHI_PRIVATE_KEY'):
        print("❌ Missing Secrets!")
        return

    print(f"📊 Checking live prices for {TARGET_TICKER}...")
    market_resp = make_kalshi_request("GET", f"/markets/{TARGET_TICKER}")
    if market_resp.status_code != 200:
        print("⚠️ Could not read market data.")
        return
        
    market_data = market_resp.json().get('market', {})
    try:
        yes_ask = int(float(market_data.get('yes_ask_dollars', '1.00')) * 100)
        yes_bid = int(float(market_data.get('yes_bid_dollars', '0.00')) * 100)
    except ValueError:
        yes_ask, yes_bid = 100, 0
    print(f"📈 Live Market -> Buy at: {yes_ask}¢ | Sell at: {yes_bid}¢")

    print("💼 Checking your Kalshi portfolio...")
    pos_resp = make_kalshi_request("GET", "/portfolio/positions")
    current_contracts = 0
    if pos_resp.status_code == 200:
        positions = pos_resp.json().get('market_positions', [])
        for p in positions:
            if p.get('ticker') == TARGET_TICKER:
                current_contracts = int(float(p.get('position_fp', '0')))
    
    current_value_dollars = (current_contracts * yes_bid) / 100
    print(f"💰 You currently own {current_contracts} contracts (Est Value: ${current_value_dollars:.2f})")

    if current_contracts > 0:
        if yes_bid >= HARVEST_PRICE:
            print(f"🌾 HARVEST TIME! Bid is {yes_bid}¢. Taking the profit!")
            action = "sell"
        elif yes_bid <= STOP_LOSS_PRICE and yes_bid > 0:
            print(f"🚨 STOP-LOSS TRIGGERED! Bid dropped to {yes_bid}¢. Ejecting to save capital!")
            action = "sell"
        else:
            action = None

        if action == "sell":
            sell_payload = {"ticker": TARGET_TICKER, "action": "sell", "side": "yes", "count": current_contracts, "type": "market", "client_order_id": str(uuid.uuid4())}
            sell_resp = make_kalshi_request("POST", "/portfolio/orders", sell_payload)
            if sell_resp.status_code in [200, 201]: print("✅ BOOM! SOLD. Position closed.")
            else: print(f"❌ Sell failed: {sell_resp.text}")
            return 

    if current_value_dollars >= MAX_POSITION_DOLLARS:
        print(f"🛡️ Max position limit (${MAX_POSITION_DOLLARS}) reached. Holding steady.")
        return
        
    if yes_ask <= BUY_PRICE_LIMIT:
        dollars_room = MAX_POSITION_DOLLARS - current_value_dollars
        target_buy_dollars = min(TRADE_AMOUNT_DOLLARS, dollars_room)
        contracts_to_buy = int((target_buy_dollars * 100) / yes_ask)
        
        if contracts_to_buy < 1:
            print("Not enough room to buy more.")
            return

        print(f"🛒 Price is good ({yes_ask}¢). Buying {contracts_to_buy} contracts...")
        buy_payload = {"ticker": TARGET_TICKER, "action": "buy", "side": "yes", "count": contracts_to_buy, "type": "market", "yes_price": BUY_PRICE_LIMIT, "client_order_id": str(uuid.uuid4())}
        buy_resp = make_kalshi_request("POST", "/portfolio/orders", buy_payload)
        if buy_resp.status_code in [200, 201]: print("✅ BOOM! BOUGHT MORE.")
        else: print(f"❌ Buy failed: {buy_resp.text}")
    else:
        print(f"⏳ Market too expensive ({yes_ask}¢). Waiting for a dip.")

if __name__ == "__main__":
    run_politics_sniper()
