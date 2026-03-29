import os
import requests
import time
import uuid

# --- REFINED SNIPER CONFIG ---
MIN_CONFIDENCE = 0.585  
TRADE_AMOUNT = 20       

def run_sniper():
    print(f"🎯 AUTHENTICATED SNIPER: {time.strftime('%X')} CT")
    api_key = os.getenv('KALSHI_API_KEY')
    
    # Using the high-speed 2026 elections endpoint
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json" # Mandatory in 2026
    }
    
    # LIVE TICKER: Ken Paxton (Texas Senate)
    target_ticker = "KXSENATETXR-26-KP" 

    # Every order in 2026 REQUIRES a unique client_order_id for security
    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, # Approx $20.70 at current 69c market
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending SECURE Market Buy for {target_ticker}...")
        response = requests.post(f"{base_url}/portfolio/orders", 
                                 json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! SUCCESS! Check your Kalshi App NOW.")
            print(f"Order ID: {response.json().get('order_id')}")
        else:
            print(f"❌ REJECTED: Status {response.status_code}")
            print(f"Reason: {response.text}")
            
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

if __name__ == "__main__":
    run_sniper()
