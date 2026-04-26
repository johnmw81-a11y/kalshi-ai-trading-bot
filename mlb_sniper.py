import os
import requests
import time
import uuid
import datetime
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# --- MLB AUTO-HUNTER CONFIG ---
MAX_POSITION_DOLLARS = 45
TRADE_AMOUNT_DOLLARS = 20

# --- THE PRO SHIELDS ---
BUY_PRICE_LIMIT = 55
HARVEST_PRICE = 80
STOP_LOSS_PRICE = 35

# --- DAY-OF FILTERS (NEW) ---
# Only trade markets that close within this window. 12h means "today's slate only"
# when the bot runs in the morning/midday. Lower this to 6 to be stricter.
CLOSE_WITHIN_HOURS = 12

# Don't ENTER new positions if first pitch is too close (existing positions still
# get harvest/stop-loss treatment). Prevents getting picked off after lineups
# move or the game starts.
MIN_MINUTES_TO_CLOSE = 30

# Skip illiquid markets — slippage and noise eat any edge.
MIN_VOLUME_24H = 500

def sign_request(private_key_str, timestamp, method, path):
    private_key = serialization.load_pem_private_key(private_key_str.encode('utf-8'), password=None)
    msg_string = timestamp + method + path
    signature = private_key.sign(msg_string.encode('utf-8'), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return base64.b64encode(signature).decode('utf-8')

def make_kalshi_request(method, path, payload=None):
    api_key_id = os.getenv('KALSHI_KEY_ID')
    private_key_str = os.getenv('KALSHI_PRIVATE_KEY')
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    signature = sign_request(private_key_str, timestamp, method, "/trade-api/v2" + path)
    headers = {"KALSHI-ACCESS-KEY": api_key_id, "KALSHI-ACCESS-SIGNATURE": signature, "KALSHI-ACCESS-TIMESTAMP": timestamp, "Content-Type": "application/json"}
    url = f"{base_url}{path}"
    if method == "GET": return requests.get(url, headers=headers)
    elif method == "POST": return requests.post(url, json=payload, headers=headers)

def parse_close_time(close_str):
    """Parse Kalshi's ISO 8601 close_time. Returns timezone-aware UTC datetime, or None on failure."""
    if not close_str:
        return None
    try:
        # Kalshi returns "2026-04-26T19:05:00Z" format
        return datetime.datetime.fromisoformat(close_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

def run_mlb_auto_hunter():
    print(f"⚾ MLB AUTO-HUNTER WAKING UP: {time.strftime('%X')} CT")
    if not os.getenv('KALSHI_KEY_ID') or not os.getenv('KALSHI_PRIVATE_KEY'):
        print("❌ Missing Secrets!")
        return

    # 1. 📡 AUTOPILOT RADAR
    print("📡 Scanning Kalshi radar for active MLB games...")
    markets_resp = make_kalshi_request("GET", "/markets?series_ticker=KXMLBGAME&status=open&limit=100")
    active_tickers = []
    skipped_future = 0
    skipped_too_close = 0
    skipped_illiquid = 0

    if markets_resp and markets_resp.status_code == 200:
        markets_data = markets_resp.json().get('markets', [])
        now = datetime.datetime.now(datetime.timezone.utc)

        for m in markets_data:
            ticker = m.get('ticker')
            if not ticker:
                continue

            # --- DAY-OF FILTER ---
            close_time = parse_close_time(m.get('close_time'))
            if not close_time:
                continue
            minutes_to_close = (close_time - now).total_seconds() / 60.0

            # Already closed or about to start — skip new entries
            if minutes_to_close <= MIN_MINUTES_TO_CLOSE:
                skipped_too_close += 1
                continue

            # Game is too far in the future — this is the day-of guard
            if minutes_to_close > CLOSE_WITHIN_HOURS * 60:
                skipped_future += 1
                continue

            # --- LIQUIDITY FILTER ---
            # Kalshi exposes 'volume' (lifetime) and sometimes 'volume_24h'. Use whichever is available.
            volume_24h = m.get('volume_24h') or m.get('volume') or 0
            if volume_24h < MIN_VOLUME_24H:
                skipped_illiquid += 1
                continue

            active_tickers.append(ticker)

        print(f"🎯 Radar locked onto {len(active_tickers)} qualifying MLB markets "
              f"(skipped: {skipped_future} future, {skipped_too_close} too close, {skipped_illiquid} illiquid)")
    else:
        print("⚠️ Radar interference: Could not fetch games from Kalshi.")
        return

    if not active_tickers:
        print("💤 No qualifying MLB games right now (none closing within "
              f"{CLOSE_WITHIN_HOURS}h with volume ≥ {MIN_VOLUME_24H}). Going back to sleep.")
        return

    # 2. 💼 GRAB PORTFOLIO & TRACK INVESTED GAMES
    print("💼 Fetching your master Kalshi portfolio...")
    pos_resp = make_kalshi_request("GET", "/portfolio/positions")
    all_positions = []
    invested_base_games = set()  # Memory bank for games we already bet on

    if pos_resp and pos_resp.status_code == 200:
        all_positions = pos_resp.json().get('market_positions', [])
        for p in all_positions:
            pos_ticker = p.get('ticker', '')
            pos_count = int(float(p.get('position_fp', '0')))
            if pos_count > 0:
                # Chops off the final team abbreviation to get the base game ID
                base_game = pos_ticker.rsplit('-', 1)[0]
                invested_base_games.add(base_game)

    # 3. 🔄 LOOP THROUGH EVERY GAME
    for ticker in active_tickers:
        print(f"\n----------------------------------------")
        print(f"🎯 ANALYZING: {ticker}")

        # Identify the base game for the current ticker we are looking at
        current_base_game = ticker.rsplit('-', 1)[0]

        market_resp = make_kalshi_request("GET", f"/markets/{ticker}")
        if market_resp.status_code != 200:
            continue

        market_data = market_resp.json().get('market', {})
        try:
            yes_ask = int(float(market_data.get('yes_ask_dollars', '1.00')) * 100)
            yes_bid = int(float(market_data.get('yes_bid_dollars', '0.00')) * 100)
        except ValueError:
            yes_ask, yes_bid = 100, 0

        print(f"📈 Live Market -> Buy at: {yes_ask}¢ | Sell at: {yes_bid}¢")

        current_contracts = 0
        for p in all_positions:
            if p.get('ticker') == ticker:
                current_contracts = int(float(p.get('position_fp', '0')))

        current_value_dollars = (current_contracts * yes_bid) / 100
        print(f"💰 You currently own {current_contracts} contracts (Est Value: ${current_value_dollars:.2f})")

        # --- SHIELDS & LOGIC ---
        if current_contracts > 0:
            if yes_bid >= HARVEST_PRICE:
                print(f"🌾 HARVEST TIME! Bid is {yes_bid}¢. Taking the profit!")
                action = "sell"
            elif yes_bid <= STOP_LOSS_PRICE and yes_bid > 0:
                print(f"🚨 STOP-LOSS TRIGGERED! Bid dropped to {yes_bid}¢. Ejecting!")
                action = "sell"
            else:
                action = None

            if action == "sell":
                # CHANGED: limit order at current bid (no slippage). Was market order.
                sell_payload = {
                    "ticker": ticker,
                    "action": "sell",
                    "side": "yes",
                    "count": current_contracts,
                    "type": "limit",
                    "yes_price": yes_bid,
                    "client_order_id": str(uuid.uuid4()),
                }
                sell_resp = make_kalshi_request("POST", "/portfolio/orders", sell_payload)
                if sell_resp.status_code in [200, 201]: print("✅ BOOM! SOLD.")
                else: print(f"❌ Sell failed: {sell_resp.text}")
                continue

        # 🛑 If we don't own THIS team, but we already own the OTHER team, skip!
        if current_contracts == 0 and current_base_game in invested_base_games:
            print(f"🛑 Skipping: We already have money on the other side of this game.")
            continue

        if current_value_dollars >= MAX_POSITION_DOLLARS:
            print(f"🛡️ Max limit reached for this team. Holding steady.")
            continue

        if yes_ask <= BUY_PRICE_LIMIT:
            dollars_room = MAX_POSITION_DOLLARS - current_value_dollars
            target_buy_dollars = min(TRADE_AMOUNT_DOLLARS, dollars_room)
            contracts_to_buy = int((target_buy_dollars * 100) / yes_ask)
            if contracts_to_buy > 0:
                print(f"🛒 Price is good ({yes_ask}¢). Buying {contracts_to_buy} contracts (limit @ {yes_ask}¢)...")
                # CHANGED: limit order at current ask (no slippage). Was market order with phantom yes_price=55.
                buy_payload = {
                    "ticker": ticker,
                    "action": "buy",
                    "side": "yes",
                    "count": contracts_to_buy,
                    "type": "limit",
                    "yes_price": yes_ask,
                    "client_order_id": str(uuid.uuid4()),
                }
                buy_resp = make_kalshi_request("POST", "/portfolio/orders", buy_payload)
                if buy_resp.status_code in [200, 201]:
                    print("✅ BOOM! BOUGHT MORE.")
                    # Mark this game as invested immediately so we don't buy the other team later in the loop!
                    invested_base_games.add(current_base_game)
                else:
                    print(f"❌ Buy failed: {buy_resp.text}")
        else:
            print(f"⏳ Market too expensive ({yes_ask}¢). Waiting for a dip.")

        time.sleep(1)  # Breathe for 1 second between games so Kalshi doesn't block us

if __name__ == "__main__":
    run_mlb_auto_hunter()
