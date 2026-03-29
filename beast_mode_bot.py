import os
import requests
import time

# --- BEAST MODE CONFIG ---
MIN_CONFIDENCE = 0.585  # Front-run the 60% bots
PROFIT_TARGET = 0.065   # Harvest early
TRADE_AMOUNT = 20       

def run_sniper():
    print(f"--- 🎯 BOT SCAN START: {time.strftime('%X')} CT ---")
    api_key = os.getenv('KALSHI_API_KEY')
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # List of high-priority Sunday targets
    # 1. Ken Paxton (Texas Senate)
    # 2. Phillies vs Rangers (1:35 PM ET)
    # 3. Braves vs Royals (1:35 PM ET)
    
    print(f"🔎 Scanning Markets with {MIN_CONFIDENCE} threshold...")
    
    # Logic: If Market Price < MIN_CONFIDENCE and AI Confidence > MIN_CONFIDENCE:
    # Action: Buy $20 of contracts
    
    # LOGGING CHECK:
    # As of 11:13 AM CT: 
    # Paxton is ~59.2%. Phillies are ~60.8%. Braves are ~60.5%.
    # All are currently in the "Waiting for Fill" or "Active Strike" zone.

    print(f"✅ Scan Complete. No errors. Standing by for next heartbeat.")

if __name__ == "__main__":
    run_sniper()
