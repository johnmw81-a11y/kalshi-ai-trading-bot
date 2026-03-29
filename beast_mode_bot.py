import os
import requests
import time
import uuid

# --- LIVE EXECUTION CONFIG ---
MIN_CONFIDENCE = 0.52   
TRADE_AMOUNT = 20       

def run_sniper():
    print(f"🔥 FINAL ATTEMPT LIVE: {time.strftime('%X')} CT")
    api_key = os.getenv('KALSHI_API_KEY')
    # The 'elections' subdomain is the new standard for ALL Kalshi v2 trades
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # This is the exact live ticker for the Paxton Nomination Market
    target_ticker = "KXSENATETXR-26-KP" 

    # Kalshi REQUIRES a unique client_order_id for every single attempt
    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, # ~ $21.00 at 70 cents
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending Authenticated MARKET BUY for {target_ticker}...")
        response = requests.post(f"{base_url}/portfolio/orders", 
                                 json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! SUCCESS! Order confirmed by Kalshi.")
            print(f"Order Details: {response.json()}")
        else:
            print(f"❌ REJECTED: Status {response.status_code}")
            print(f"Message: {response.text}")
            
    except Exception as e:
        print(f"⚠️ API Error: {e}")

if __name__ == "__main__":
    run_sniper()
