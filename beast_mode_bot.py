import os
import requests
import time
import uuid
import datetime

# --- REFINED SNIPER CONFIG ---
MIN_CONFIDENCE = 0.585  
TRADE_AMOUNT = 20       

def run_sniper():
    print(f"🎯 AUTHENTICATED SNIPER: {time.strftime('%X')} CT")
    
    # Required for 2026 Security
    api_key = os.getenv('KALSHI_API_KEY')
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    # This header is the NEW requirement for 2026 Market Orders
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # LIVE TICKER: Ken Paxton 2026
    # Note: Tickers are now Case-Sensitive in the 2026 API
    target_ticker = "KXSENATETXR-26-KP" 

    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, # Approx $21.00
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending SECURE Market Buy for {target_ticker}...")
        # We are using the V2 'portfolio/orders' endpoint
        response = requests.post(f"{base_url}/portfolio/orders", 
                                 json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! Trade Executed. Check Kalshi Portfolio.")
        elif response.status_code == 401:
            print("❌ ERROR: Your API Key is rejected. Check GitHub Secrets.")
        elif response.status_code == 400:
            print(f"❌ REJECTED: Check Ticker or Balance. {response.text}")
        else:
            print(f"❌ UNKNOWN: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

if __name__ == "__main__":
    run_sniper()
