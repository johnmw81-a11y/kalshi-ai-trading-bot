import os
import json
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
HARVEST_PRICE = 80          # sell at this bid or higher (take profit)
STOP_LOSS_PRICE = 35        # sell at this bid or lower (cut loss)

# --- DAY-OF FILTERS ---
CLOSE_WITHIN_HOURS = 12     # only trade markets closing within this window
MIN_MINUTES_TO_CLOSE = 30   # don't enter if first pitch is too close
MIN_VOLUME_24H = 500        # skip illiquid markets

# --- EDGE FILTERS (NEW) ---
# Only enter a position when there's at least this much edge vs the de-juiced
# consensus moneyline from real sportsbooks. 4¢ is conservative for MLB.
MIN_EDGE_CENTS = 4

# Reasonable price band. MIN keeps us out of deep-dog gamble territory.
# MAX allows fading heavy favorites (the validated NO-side edge from the
# Safe Compounder strategy) — 80¢ NO buys are essentially "fade a 20¢ YES".
MIN_BUY_PRICE = 30          # don't buy below this (deep underdog territory)
MAX_BUY_PRICE = 80          # allow Safe-Compounder-style fades up to here

# --- AI CONFIDENCE GATE (NEW) ---
USE_AI_GATE = True          # set False to skip the AI check (saves xAI credits)
MIN_AI_CONFIDENCE = 0.6     # only trade if AI confidence >= this

# --- ODDS API ---
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_SPORT = "baseball_mlb"
ODDS_API_REGION = "us"

# Odds cache — written to disk so multiple bot runs share data and we conserve
# the 500-request/month free tier. TTL of 30 min; odds rarely move that fast.
_odds_cache = None
ODDS_CACHE_TTL_SECONDS = 30 * 60
ODDS_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.',
    '.odds_cache.json'
)


# --- KALSHI TEAM ABBREV → ODDS API TEAM NAME ---
# Kalshi MLB tickers look like KXMLBGAME-25APR26-NYY (last segment is the team
# abbreviation that won YES). The odds API uses full team names, so we map.
KALSHI_TO_ODDS_TEAM = {
    'ARI': 'Arizona Diamondbacks',
    'ATL': 'Atlanta Braves',
    'BAL': 'Baltimore Orioles',
    'BOS': 'Boston Red Sox',
    'CHC': 'Chicago Cubs',
    'CWS': 'Chicago White Sox',
    'CHW': 'Chicago White Sox',
    'CIN': 'Cincinnati Reds',
    'CLE': 'Cleveland Guardians',
    'COL': 'Colorado Rockies',
    'DET': 'Detroit Tigers',
    'HOU': 'Houston Astros',
    'KC':  'Kansas City Royals',
    'KCR': 'Kansas City Royals',
    'LAA': 'Los Angeles Angels',
    'LAD': 'Los Angeles Dodgers',
    'MIA': 'Miami Marlins',
    'MIL': 'Milwaukee Brewers',
    'MIN': 'Minnesota Twins',
    'NYM': 'New York Mets',
    'NYY': 'New York Yankees',
    'ATH': 'Oakland Athletics',
    'OAK': 'Oakland Athletics',
    'PHI': 'Philadelphia Phillies',
    'PIT': 'Pittsburgh Pirates',
    'SD':  'San Diego Padres',
    'SDP': 'San Diego Padres',
    'SF':  'San Francisco Giants',
    'SFG': 'San Francisco Giants',
    'SEA': 'Seattle Mariners',
    'STL': 'St. Louis Cardinals',
    'TB':  'Tampa Bay Rays',
    'TBR': 'Tampa Bay Rays',
    'TEX': 'Texas Rangers',
    'TOR': 'Toronto Blue Jays',
    'WSH': 'Washington Nationals',
    'WAS': 'Washington Nationals',
}


def american_to_prob(american_odds):
    """American moneyline -> implied probability (0-1)."""
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def _load_odds_cache_from_disk():
    """Return cached odds list if file exists and is fresh, else None."""
    try:
        with open(ODDS_CACHE_PATH, 'r') as f:
            blob = json.load(f)
        age = time.time() - blob.get('timestamp', 0)
        if age <= ODDS_CACHE_TTL_SECONDS:
            return blob.get('data')
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _write_odds_cache_to_disk(data):
    try:
        with open(ODDS_CACHE_PATH, 'w') as f:
            json.dump({'timestamp': time.time(), 'data': data}, f)
    except OSError as e:
        print(f"   ⚠️ Could not write odds cache: {e}")


def fetch_mlb_odds():
    """Pull MLB moneylines from the-odds-api.com, average across books, de-juice.
    Returns list of dicts with home/away team names + de-juiced fair probabilities.
    Returns [] on any failure (which causes the bot to skip all NEW entries —
    existing positions still get harvest/stop-loss treatment)."""
    global _odds_cache
    if _odds_cache is not None:
        return _odds_cache

    # Try disk cache first to conserve the 500/month free-tier quota
    disk = _load_odds_cache_from_disk()
    if disk is not None:
        _odds_cache = disk
        print(f"📊 Using cached odds for {len(disk)} games (cache age < {ODDS_CACHE_TTL_SECONDS//60} min)")
        return _odds_cache

    api_key = os.getenv('ODDS_API_KEY')
    if not api_key:
        print("⚠️ ODDS_API_KEY not set — bot will not enter NEW positions this run.")
        _odds_cache = []
        return _odds_cache

    url = f"{ODDS_API_BASE}/sports/{ODDS_API_SPORT}/odds"
    params = {
        'apiKey': api_key,
        'regions': ODDS_API_REGION,
        'markets': 'h2h',
        'oddsFormat': 'american',
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Odds API HTTP {resp.status_code}: {resp.text[:200]}")
            _odds_cache = []
            return _odds_cache

        games = resp.json()
        processed = []
        for g in games:
            home = g.get('home_team')
            away = g.get('away_team')
            commence = g.get('commence_time')

            home_probs = []
            away_probs = []
            for bm in g.get('bookmakers', []):
                for market in bm.get('markets', []):
                    if market.get('key') != 'h2h':
                        continue
                    outcomes = {o['name']: o['price'] for o in market.get('outcomes', [])}
                    if home in outcomes and away in outcomes:
                        h = american_to_prob(outcomes[home])
                        a = american_to_prob(outcomes[away])
                        # De-juice: rescale so probs sum to 1
                        total = h + a
                        if total > 0:
                            home_probs.append(h / total)
                            away_probs.append(a / total)

            if home_probs:
                processed.append({
                    'home': home,
                    'away': away,
                    'commence_time': commence,
                    'fair_home_prob': sum(home_probs) / len(home_probs),
                    'fair_away_prob': sum(away_probs) / len(away_probs),
                    'num_books': len(home_probs),
                })

        _odds_cache = processed
        _write_odds_cache_to_disk(processed)
        print(f"📊 Loaded de-juiced odds for {len(processed)} MLB games (fresh from API)")
        # Track API usage
        used = resp.headers.get('x-requests-used', '?')
        remaining = resp.headers.get('x-requests-remaining', '?')
        print(f"   Odds API usage: {used} used, {remaining} remaining this month")
        return _odds_cache
    except Exception as e:
        print(f"⚠️ Odds API fetch error: {e}")
        _odds_cache = []
        return _odds_cache


def get_fair_yes_prob(ticker, odds_data):
    """Given a Kalshi ticker and odds data, return the de-juiced fair probability
    that the YES side wins (the team named in the ticker). Returns None if not found."""
    parts = ticker.split('-')
    if len(parts) < 2:
        return None
    team_abbrev = parts[-1]
    team_name = KALSHI_TO_ODDS_TEAM.get(team_abbrev)
    if not team_name:
        print(f"   ⚠️ No team mapping for abbreviation: {team_abbrev}")
        return None

    for game in odds_data:
        if game['home'] == team_name:
            return game['fair_home_prob']
        if game['away'] == team_name:
            return game['fair_away_prob']
    return None


def ai_confidence_check(ticker, side, kalshi_price_cents, fair_prob_pct, edge_cents):
    """Single-model AI check via xAI / Grok. Returns float 0-1.
    Returns 1.0 (auto-pass) if AI key missing or any error — fail-open.
    Returns 0.0 only when AI explicitly says no."""
    if not USE_AI_GATE:
        return 1.0

    api_key = os.getenv('XAI_API_KEY')
    if not api_key:
        return 1.0  # no AI key configured, skip the gate

    prompt = f"""You are evaluating an MLB prediction-market bet on Kalshi.

TICKER: {ticker}
SIDE: {side.upper()}
KALSHI PRICE: {kalshi_price_cents}¢
DE-JUICED CONSENSUS FAIR PROBABILITY: {fair_prob_pct}¢
DETECTED EDGE: {edge_cents}¢ (Kalshi appears to be mispricing vs sportsbook consensus)

Use general baseball knowledge to evaluate confidence: starting pitcher matchup, team form, weather/postponement risk, situational factors (travel, rest, day game after night game). The consensus odds already account for most of this, so only deviate from the edge signal if you have specific reason.

Return ONLY a JSON object with keys "confidence" (0.0 to 1.0) and "reason" (one sentence).
No other text, no markdown fences."""

    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-3",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 200,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️ AI gate HTTP {resp.status_code} — auto-passing")
            return 1.0
        text = resp.json()['choices'][0]['message']['content'].strip()
        # Strip markdown code fences if model added them.
        # Using chr(96) instead of literal backticks for portability.
        fence = chr(96) * 3
        if text.startswith(fence):
            text = text[3:]
            if text.lower().startswith('json'):
                text = text[4:]
            if text.endswith(fence):
                text = text[:-3]
            text = text.strip()
        data = json.loads(text)
        conf = float(data.get('confidence', 0.5))
        reason = data.get('reason', '')
        print(f"   🤖 AI confidence: {conf:.2f} — {reason}")
        return conf
    except Exception as e:
        print(f"   ⚠️ AI gate error: {e} — auto-passing")
        return 1.0


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
    if not close_str:
        return None
    try:
        return datetime.datetime.fromisoformat(close_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def run_mlb_auto_hunter():
    print(f"⚾ MLB AUTO-HUNTER WAKING UP: {time.strftime('%X')} CT")
    if not os.getenv('KALSHI_KEY_ID') or not os.getenv('KALSHI_PRIVATE_KEY'):
        print("❌ Missing Kalshi secrets!")
        return

    # Pre-fetch the day's odds (1 API call total — used for every game decision)
    odds_data = fetch_mlb_odds()

    # 1. 📡 RADAR
    print("📡 Scanning Kalshi radar for active MLB games...")
    markets_resp = make_kalshi_request("GET", "/markets?series_ticker=KXMLBGAME&status=open&limit=100")
    qualifying_tickers = []
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

            close_time = parse_close_time(m.get('close_time'))
            if not close_time:
                continue
            minutes_to_close = (close_time - now).total_seconds() / 60.0

            if minutes_to_close <= MIN_MINUTES_TO_CLOSE:
                skipped_too_close += 1
                continue
            if minutes_to_close > CLOSE_WITHIN_HOURS * 60:
                skipped_future += 1
                continue

            volume_24h = m.get('volume_24h') or m.get('volume') or 0
            if volume_24h < MIN_VOLUME_24H:
                skipped_illiquid += 1
                continue

            qualifying_tickers.append(ticker)

        print(f"🎯 Radar locked onto {len(qualifying_tickers)} qualifying MLB markets "
              f"(skipped: {skipped_future} future, {skipped_too_close} too close, {skipped_illiquid} illiquid)")
    else:
        print("⚠️ Radar interference: Could not fetch games from Kalshi.")
        return

    if not qualifying_tickers:
        print("💤 No qualifying MLB games right now. Going back to sleep.")
        return

    # 2. 💼 GRAB PORTFOLIO
    print("💼 Fetching your master Kalshi portfolio...")
    pos_resp = make_kalshi_request("GET", "/portfolio/positions")
    all_positions = []
    invested_base_games = set()

    if pos_resp and pos_resp.status_code == 200:
        all_positions = pos_resp.json().get('market_positions', [])
        for p in all_positions:
            pos_ticker = p.get('ticker', '')
            pos_count = int(float(p.get('position_fp', '0')))
            if pos_count != 0:
                base_game = pos_ticker.rsplit('-', 1)[0]
                invested_base_games.add(base_game)

    # 3. 🔄 LOOP
    for ticker in qualifying_tickers:
        print("")
        print("----------------------------------------")
        print(f"🎯 ANALYZING: {ticker}")

        current_base_game = ticker.rsplit('-', 1)[0]

        market_resp = make_kalshi_request("GET", f"/markets/{ticker}")
        if market_resp.status_code != 200:
            continue

        market_data = market_resp.json().get('market', {})
        try:
            yes_ask = int(float(market_data.get('yes_ask_dollars', '1.00')) * 100)
            yes_bid = int(float(market_data.get('yes_bid_dollars', '0.00')) * 100)
            no_ask = int(float(market_data.get('no_ask_dollars', '1.00')) * 100)
            no_bid = int(float(market_data.get('no_bid_dollars', '0.00')) * 100)
        except ValueError:
            yes_ask, yes_bid, no_ask, no_bid = 100, 0, 100, 0

        print(f"📈 YES: buy {yes_ask}¢ / sell {yes_bid}¢   |   NO: buy {no_ask}¢ / sell {no_bid}¢")

        # ===== EXISTING POSITION HARVEST/STOP =====
        current_yes_contracts = 0
        current_no_contracts = 0
        for p in all_positions:
            if p.get('ticker') == ticker:
                pos = int(float(p.get('position_fp', '0')))
                # Kalshi positions: positive = YES contracts, negative = NO contracts
                if pos > 0:
                    current_yes_contracts = pos
                elif pos < 0:
                    current_no_contracts = abs(pos)

        if current_yes_contracts > 0:
            current_value = (current_yes_contracts * yes_bid) / 100
            print(f"💰 Hold {current_yes_contracts} YES (Est ${current_value:.2f})")
            if yes_bid >= HARVEST_PRICE:
                print(f"🌾 HARVEST YES at {yes_bid}¢")
                _place_limit(ticker, "sell", "yes", current_yes_contracts, yes_bid)
                continue
            if 0 < yes_bid <= STOP_LOSS_PRICE:
                print(f"🚨 STOP-LOSS YES at {yes_bid}¢")
                _place_limit(ticker, "sell", "yes", current_yes_contracts, yes_bid)
                continue

        if current_no_contracts > 0:
            current_value = (current_no_contracts * no_bid) / 100
            print(f"💰 Hold {current_no_contracts} NO (Est ${current_value:.2f})")
            if no_bid >= HARVEST_PRICE:
                print(f"🌾 HARVEST NO at {no_bid}¢")
                _place_limit(ticker, "sell", "no", current_no_contracts, no_bid)
                continue
            if 0 < no_bid <= STOP_LOSS_PRICE:
                print(f"🚨 STOP-LOSS NO at {no_bid}¢")
                _place_limit(ticker, "sell", "no", current_no_contracts, no_bid)
                continue

        # Already on the other side of this game? Skip new entry.
        if current_yes_contracts == 0 and current_no_contracts == 0 and current_base_game in invested_base_games:
            print(f"🛑 Skip: already positioned on the other team in this game.")
            continue

        # ===== NEW ENTRY: REQUIRES FAIR-VALUE DATA =====
        if not odds_data:
            print("⏸️ No odds data — skipping new entries (existing positions still managed).")
            continue

        fair_yes_prob = get_fair_yes_prob(ticker, odds_data)
        if fair_yes_prob is None:
            print(f"⏸️ No de-juiced consensus for {ticker} — skipping.")
            continue

        fair_yes_cents = round(fair_yes_prob * 100)
        fair_no_cents = 100 - fair_yes_cents
        print(f"🧮 Fair value: YES {fair_yes_cents}¢ / NO {fair_no_cents}¢")

        # ===== EVALUATE BOTH SIDES =====
        yes_edge = fair_yes_cents - yes_ask    # positive = Kalshi underpricing YES
        no_edge = fair_no_cents - no_ask       # positive = Kalshi underpricing NO

        chosen_side = None
        chosen_price = None
        chosen_edge = None

        # Prefer the side with bigger edge, but require a minimum.
        # Also enforce a sensible price band: avoid deep dogs and near-locks.
        if yes_edge >= MIN_EDGE_CENTS and MIN_BUY_PRICE <= yes_ask <= MAX_BUY_PRICE:
            if yes_edge > (no_edge if no_edge > 0 else 0):
                chosen_side = "yes"
                chosen_price = yes_ask
                chosen_edge = yes_edge

        if chosen_side is None and no_edge >= MIN_EDGE_CENTS and MIN_BUY_PRICE <= no_ask <= MAX_BUY_PRICE:
            chosen_side = "no"
            chosen_price = no_ask
            chosen_edge = no_edge

        if chosen_side is None:
            print(f"⏳ No edge ≥ {MIN_EDGE_CENTS}¢ in band {MIN_BUY_PRICE}-{MAX_BUY_PRICE}¢. "
                  f"YES edge: {yes_edge:+d}¢, NO edge: {no_edge:+d}¢.")
            continue

        print(f"💡 Edge found: {chosen_side.upper()} at {chosen_price}¢ with +{chosen_edge}¢ edge")

        # ===== AI CONFIDENCE GATE =====
        confidence = ai_confidence_check(
            ticker,
            chosen_side,
            chosen_price,
            fair_yes_cents if chosen_side == "yes" else fair_no_cents,
            chosen_edge,
        )
        if confidence < MIN_AI_CONFIDENCE:
            print(f"   ⛔ AI confidence {confidence:.2f} < {MIN_AI_CONFIDENCE} — skipping.")
            continue

        # ===== SIZE & PLACE =====
        # Size based on existing position (re-use rule: cap per-team exposure)
        existing_dollars = (current_yes_contracts * yes_bid + current_no_contracts * no_bid) / 100
        if existing_dollars >= MAX_POSITION_DOLLARS:
            print(f"🛡️ Already at max exposure on this team. Holding.")
            continue
        dollars_room = MAX_POSITION_DOLLARS - existing_dollars
        target_buy_dollars = min(TRADE_AMOUNT_DOLLARS, dollars_room)
        contracts_to_buy = int((target_buy_dollars * 100) / chosen_price)
        if contracts_to_buy <= 0:
            continue

        print(f"🛒 Buying {contracts_to_buy} {chosen_side.upper()} contracts (limit @ {chosen_price}¢)")
        success = _place_limit(ticker, "buy", chosen_side, contracts_to_buy, chosen_price)
        if success:
            invested_base_games.add(current_base_game)

        time.sleep(1)


def _place_limit(ticker, action, side, count, price_cents):
    """Place a limit order at the given price. Returns True on success."""
    payload = {
        "ticker": ticker,
        "action": action,
        "side": side,
        "count": count,
        "type": "limit",
        "client_order_id": str(uuid.uuid4()),
    }
    # Kalshi expects yes_price for YES side, no_price for NO side
    if side == "yes":
        payload["yes_price"] = price_cents
    else:
        payload["no_price"] = price_cents

    resp = make_kalshi_request("POST", "/portfolio/orders", payload)
    if resp is not None and resp.status_code in (200, 201):
        print(f"   ✅ {action.upper()} {side.upper()} order placed.")
        return True
    err_text = resp.text[:300] if resp is not None else "no response"
    print(f"   ❌ Order failed: {err_text}")
    return False


if __name__ == "__main__":
    run_mlb_auto_hunter()
