import os
import time
import requests

# --- EVOLVED ASYMMETRIC CONFIG ---
KALSHI_API_URL = "https://trading-api.kalshi.com/trade-api/v2"
MIN_CONFIDENCE = 0.585  # Beat the 60% crowd
PROFIT_TARGET = 0.065   # Harvest early at 6.5 cents
TRADE_AMOUNT = 20       # Dollars per trade

def get_kalshi_headers():
    api_key = os.getenv('KALSHI_API_KEY')
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

def run_harvester_loop():
    print(f"🚀 Loop started at {time.strftime('%X')} CT")
    
    try:
        # 1. HARVESTER: Check for existing wins to sell
        response = requests.get(f"{KALSHI_API_URL}/portfolio/positions", headers=get_kalshi_headers())
        if response.status_code == 200:
            portfolio = response.json()
            for pos in portfolio.get('positions', []):
                ticker = pos.get('ticker')
                avg_price = float(pos.get('avg_cost_basis', 0)) / 100
                
                # Get current bid price
                m_res = requests.get(f"{KALSHI_API_URL}/markets/{ticker}", headers=get_kalshi_headers())
                if m_res.status_code == 200:
                    current_price = float(m_res.json()['market']['yes_bid']) / 100
                    if (current_price - avg_price) >= PROFIT_TARGET:
                        print(f"💰 HARVESTING: {ticker} up {current_price-avg_price:.3f}. Selling!")
                        # Order placement logic would trigger here
        else:
            print(f"⚠️ Kalshi Portfolio Check Failed: {response.status_code}")

        # 2. SNIPER: Scan for new 58.5% entries
        print(f"🔎 Scanning Politics & Sports at {MIN_CONFIDENCE} threshold...")
        # (This is where the AI confidence vs Market Price logic runs)
        # Target: Ken Paxton (Current: 59%), Phillies (-156), Braves (-154)

    except Exception as e:
        print(f"❌ Error during loop: {e}")

    print("✅ Loop finished. Waiting for next heartbeat.")

if __name__ == "__main__":
    run_harvester_loop()
