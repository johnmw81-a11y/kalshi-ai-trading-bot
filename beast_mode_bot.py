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
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    # LIVE TICKER: Found on Kalshi as of March 29, 2026
    target_ticker = "KXSENATETXR-26-KP" 

    # MANDATORY: Every order in 2026 must have a unique client_order_id
    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, # Approx $20.70 at current 69% odds
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending MARKET BUY for {target_ticker}...")
        response = requests.post(f"{base_url}/portfolio/orders", 
                                 json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! SUCCESS! Check your Kalshi App NOW.")
            print(f"Order Details: {response.json()}")
        else:
            print(f"❌ REJECTED: Status {response.status_code}")
            print(f"Reason: {response.text}")
            
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

if __name__ == "__main__":
    run_sniper()
