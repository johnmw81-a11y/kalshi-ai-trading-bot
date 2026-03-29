import os
import requests
import time

# --- LIVE EXECUTION CONFIG ---
MIN_CONFIDENCE = 0.52   # This is your "Market Buy" floor
TRADE_AMOUNT = 20       # Dollars per position

def run_sniper():
    print(f"🔥 LIVE TRADE RUN: {time.strftime('%X')} CT")
    api_key = os.getenv('KALSHI_API_KEY')
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    # 🎯 TARGET: Ken Paxton (Texas Senate)
    # Market is currently ~69%. Since 69 > 52, we strike.
    paxton_payload = {
        "ticker": "KXSENATETXR",
        "action": "buy",
        "count": 30, # Approx $20 worth
        "type": "market",
        "side": "yes"
    }

    try:
        print("🛒 Attempting to buy Ken Paxton at market...")
        response = requests.post("https://trading-api.kalshi.com/trade-api/v2/portfolio/orders", 
                                 json=paxton_payload, headers=headers)
        if response.status_code == 201 or response.status_code == 200:
            print("✅ TRADE EXECUTED! Check your Kalshi App.")
        else:
            print(f"❌ Trade Failed. Kalshi said: {response.text}")
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

if __name__ == "__main__":
    run_sniper()
