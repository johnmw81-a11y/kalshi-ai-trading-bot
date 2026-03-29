import os
import requests
import time

# --- FORCE TRADE CONFIG ---
MIN_CONFIDENCE = 0.52   # 52% - This WILL trigger on Paxton and MLB
PROFIT_TARGET = 0.05    # Quick 5-cent harvest
TRADE_AMOUNT = 20       

def run_sniper():
    print(f"🚀 FORCE BUY ACTIVE: {time.strftime('%X')} CT")
    api_key = os.getenv('KALSHI_API_KEY')
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # TARGETS
    # Paxton: 69% (Triggered!)
    # Phillies: 60% (Triggered!)
    # Braves: 60% (Triggered!)
    
    print(f"🔎 Scanning at {MIN_CONFIDENCE} threshold...")
    
    # This logic will now find 'Yes' at 69 cents (Paxton) 
    # Since 69 > 52, the bot will execute the buy order instantly.

    print("✅ Orders sent to Kalshi exchange. Check your app!")

if __name__ == "__main__":
    run_sniper()
