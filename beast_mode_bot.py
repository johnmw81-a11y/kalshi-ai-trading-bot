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
    
    # NEW 2026 STANDARDS: All trades must use the elections subdomain
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    # These headers are now mandatory for Market Orders in 2026
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # LIVE TICKER: Found for Ken Paxton as of 1:35 PM
    target_ticker = "KXSENATETXR-26-KP" 

    # Every order REQUIRES a unique client_order_id in 2026
    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, # Approx $21.00 at 70c
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending SECURE Market Buy for {target_ticker}...")
        response = requests.post(f"{base_url}/portfolio/orders", 
                                 json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! SUCCESS! Trade confirmed. Check Kalshi Portfolio.")
        else:
            print(f"❌ REJECTED: Status {response.status_code}")
            print(f"Reason: {response.text}")
            
    except Exception as e:
        print(f"⚠️ API Connection Error: {e}")

if __name__ == "__main__":
    run_sniper()
