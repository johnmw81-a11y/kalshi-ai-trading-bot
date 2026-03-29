import os
import time
import requests

# --- CONFIGURATION ---
KALSHI_API_URL = "https://trading-api.kalshi.com/trade-api/v2"
MIN_CONFIDENCE = 0.60  
PROFIT_TARGET = 0.07   
TRADE_AMOUNT = 20      

def get_kalshi_headers():
    # Ensure the key exists to avoid immediate crash
    api_key = os.getenv('KALSHI_API_KEY')
    if not api_key:
        print("❌ ERROR: KALSHI_API_KEY is missing from Secrets!")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

def run_harvester_loop():
    print(f"🚀 Loop started at {time.strftime('%X')} CT")
    
    try:
        # 1. GET CURRENT POSITIONS
        response = requests.get(f"{KALSHI_API_URL}/portfolio/positions", headers=get_kalshi_headers())
        
        # Check if Kalshi actually answered correctly (Status Code 200)
        if response.status_code != 200:
            print(f"⚠️ Kalshi API rejected the request. Status: {response.status_code}")
            print(f"Response: {response.text}")
            return # Exit the loop gracefully instead of crashing

        portfolio = response.json()
        
        # If we have positions, look to HARVEST
        for pos in portfolio.get('positions', []):
            ticker = pos.get('ticker')
            avg_price = float(pos.get('avg_cost_basis', 0)) / 100
            
            # Get current market price for that ticker
            m_res = requests.get(f"{KALSHI_API_URL}/markets/{ticker}", headers=get_kalshi_headers())
            if m_res.status_code == 200:
                m_data = m_res.json()
                current_price = float(m_data['market']['yes_bid']) / 100
                
                if (current_price - avg_price) >= PROFIT_TARGET:
                    print(f"💰 HARVESTING: {ticker} profit detected. Sending Sell Order...")
                    # [Sell logic would fire here]

    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")

    # 2. SNIPER LOGIC
    print("🔎 Scanning markets for new Sniper entries...")
    # (The AI scanning logic continues here)

    print("✅ Loop finished. Standing by.")

if __name__ == "__main__":
    run_harvester_loop()
