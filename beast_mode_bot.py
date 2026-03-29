import os
import requests
import time
import uuid
import datetime
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

def sign_request(private_key_str, timestamp, method, path):
    # Load the private key from your GitHub Secret
    private_key = serialization.load_pem_private_key(
        private_key_str.encode('utf-8'), 
        password=None
    )
    # Create the signature string Kalshi requires
    msg_string = timestamp + method + path
    signature = private_key.sign(
        msg_string.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

def run_sniper():
    print(f"🎯 RSA AUTHENTICATED SNIPER: {time.strftime('%X')} CT")
    
    # Pull the two new secrets
    api_key_id = os.getenv('KALSHI_KEY_ID')
    private_key_str = os.getenv('KALSHI_PRIVATE_KEY')
    
    if not api_key_id or not private_key_str:
        print("❌ Missing KALSHI_KEY_ID or KALSHI_PRIVATE_KEY in GitHub Secrets.")
        return

    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    target_ticker = "KXSENATETXR-26-KP" 
    path = "/portfolio/orders"
    
    # Generate the cryptographic signature
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    signature = sign_request(private_key_str, timestamp, "POST", "/trade-api/v2" + path)
    
    # The NEW mandatory headers for Kalshi
    headers = {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    order_payload = {
        "ticker": target_ticker,
        "action": "buy",
        "side": "yes",
        "count": 30, 
        "type": "market",
        "client_order_id": str(uuid.uuid4()) 
    }

    try:
        print(f"🛒 Sending RSA-Signed Market Buy for {target_ticker}...")
        response = requests.post(f"{base_url}{path}", json=order_payload, headers=headers)
        
        if response.status_code in [200, 201]:
            print("✅ BOOM! SUCCESS! Trade confirmed.")
            print(response.json())
        else:
            print(f"❌ REJECTED: Status {response.status_code}")
            print(f"Reason: {response.text}")
            
    except Exception as e:
        print(f"⚠️ API Error: {e}")

if __name__ == "__main__":
    run_sniper()
