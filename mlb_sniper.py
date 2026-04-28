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

# =============================================================================
# CONFIG
# =============================================================================

# --- BANKROLL-SCALED POSITION SIZING (NEW) ---
# Trades are sized as a percentage of current Kalshi balance.
# This lets gains compound and provides natural protection on drawdowns.
TRADE_AMOUNT_PCT = 2.0          # 2% of bankroll per trade
MAX_POSITION_PCT = 5.0          # 5% of bankroll cap per team
MIN_TRADE_AMOUNT_DOLLARS = 5    # never go below this (Kalshi has min order sizes)
MAX_TRADE_AMOUNT_DOLLARS = 200  # safety cap regardless of bankroll
# Fallback values used only if the balance API fails:
FALLBACK_TRADE_AMOUNT_DOLLARS = 20
FALLBACK_MAX_POSITION_DOLLARS = 45

# --- THE PRO SHIELDS ---
HARVEST_PRICE = 80              # sell at this bid or higher (take profit)
STOP_LOSS_FLOOR = 35            # absolute floor: always exit if bid drops below this
STOP_LOSS_DROP_CENTS = 25       # NEW: also exit if bid drops this many cents from entry

# --- DAY-OF FILTERS ---
CLOSE_WITHIN_HOURS = 9999
MIN_MINUTES_TO_CLOSE = 30
MIN_VOLUME_24H = 0

# --- EDGE FILTERS ---
MIN_EDGE_CENTS = 3
MIN_BUY_PRICE = 20
MAX_BUY_PRICE = 85

# --- AI CONFIDENCE GATE ---
USE_AI_GATE = True
MIN_AI_CONFIDENCE = 0.6
# Ensemble weights — Grok and Gemini debate every trade. If only one key is
# available, that model's confidence is used directly. Tweak weights if you
# trust one model over the other.
GROK_WEIGHT = 0.6
GEMINI_WEIGHT = 0.4

# --- MARKET DEPTH CHECK (NEW in v4) ---
USE_DEPTH_CHECK = True
MAX_BID_ASK_SPREAD_CENTS = 5    # skip if spread on chosen side > this
MIN_TOP_OF_BOOK_SIZE = 10       # skip if best bid/ask has fewer contracts than this

# --- TRADE LOGGING (NEW in v4) ---
USE_TRADE_LOGGING = True
TRADE_LOG_PATH_RELATIVE = '.trade_log.csv'

# --- ODDS API ---
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_SPORT = "baseball_mlb"
ODDS_API_REGION = "us"

# --- DISK CACHES (persist between GitHub Actions runs via actions/cache) ---
CACHE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.'
ODDS_CACHE_PATH = os.path.join(CACHE_DIR, '.odds_cache.json')
ENTRY_PRICES_PATH = os.path.join(CACHE_DIR, '.entry_prices.json')
TRADE_LOG_PATH = os.path.join(CACHE_DIR, TRADE_LOG_PATH_RELATIVE)
ODDS_CACHE_TTL_SECONDS = 30 * 60

_odds_cache = None
_entry_prices = None
_balance_cache = None

# --- PITCHER CHECK (NEW) ---
USE_PITCHER_CHECK = True
MLB_STATS_API = "https://statsapi.mlb.com/api/v1"

# --- WEATHER CHECK (NEW) ---
USE_WEATHER_CHECK = True
MAX_RAIN_PROBABILITY = 50       # skip game if rain probability > this %
WEATHER_API = "https://api.open-meteo.com/v1/forecast"


# =============================================================================
# LOOKUP TABLES
# =============================================================================

# Kalshi MLB ticker abbrev -> the-odds-api team name
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

# Kalshi MLB ticker abbrev -> MLB Stats API team ID (for pitcher check)
KALSHI_TO_MLB_TEAM_ID = {
    'ARI': 109, 'ATL': 144, 'BAL': 110, 'BOS': 111, 'CHC': 112, 'CWS': 145, 'CHW': 145,
    'CIN': 113, 'CLE': 114, 'COL': 115, 'DET': 116, 'HOU': 117, 'KC': 118, 'KCR': 118,
    'LAA': 108, 'LAD': 119, 'MIA': 146, 'MIL': 158, 'MIN': 142, 'NYM': 121, 'NYY': 147,
    'ATH': 133, 'OAK': 133, 'PHI': 143, 'PIT': 134, 'SD': 135, 'SDP': 135, 'SF': 137,
    'SFG': 137, 'SEA': 136, 'STL': 138, 'TB': 139, 'TBR': 139, 'TEX': 140, 'TOR': 141,
    'WSH': 120, 'WAS': 120,
}

# Home stadium coords (lat, lon) for weather lookup
STADIUM_COORDS = {
    'ARI': (33.4453, -112.0667),  'ATL': (33.8908, -84.4678),
    'BAL': (39.2839, -76.6219),   'BOS': (42.3467, -71.0972),
    'CHC': (41.9484, -87.6553),   'CWS': (41.8300, -87.6339),  'CHW': (41.8300, -87.6339),
    'CIN': (39.0973, -84.5072),   'CLE': (41.4962, -81.6852),
    'COL': (39.7559, -104.9942),  'DET': (42.3390, -83.0485),
    'HOU': (29.7572, -95.3553),   'KC': (39.0517, -94.4803),  'KCR': (39.0517, -94.4803),
    'LAA': (33.8003, -117.8827),  'LAD': (34.0739, -118.2400),
    'MIA': (25.7781, -80.2197),   'MIL': (43.0280, -87.9712),
    'MIN': (44.9817, -93.2776),   'NYM': (40.7571, -73.8458),
    'NYY': (40.8296, -73.9262),   'ATH': (37.7516, -122.2005),  'OAK': (37.7516, -122.2005),
    'PHI': (39.9061, -75.1665),   'PIT': (40.4469, -80.0057),
    'SD': (32.7073, -117.1566),   'SDP': (32.7073, -117.1566),
    'SF': (37.7786, -122.3893),   'SFG': (37.7786, -122.3893),
    'SEA': (47.5914, -122.3325),  'STL': (38.6226, -90.1928),
    'TB': (27.7683, -82.6534),    'TBR': (27.7683, -82.6534),
    'TEX': (32.7510, -97.0828),   'TOR': (43.6414, -79.3894),
    'WSH': (38.8730, -77.0074),   'WAS': (38.8730, -77.0074),
}


# =============================================================================
# KALSHI HELPERS (existing, unchanged)
# =============================================================================

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


# =============================================================================
# BANKROLL (NEW)
# =============================================================================

def get_kalshi_balance_cents():
    """Fetch current Kalshi balance in cents. Returns None on failure (caller falls back to defaults)."""
    global _balance_cache
    if _balance_cache is not None:
        return _balance_cache
    try:
        resp = make_kalshi_request("GET", "/portfolio/balance")
        if resp is None or resp.status_code != 200:
            print(f"   ⚠️ Balance fetch returned status: {resp.status_code if resp else 'no response'}")
            return None
        data = resp.json()
        # Kalshi returns balance in cents. Field name historically: balance
        balance_cents = data.get('balance') or data.get('balance_cents') or 0
        _balance_cache = int(balance_cents)
        print(f"💵 Kalshi balance: ${_balance_cache/100:.2f}")
        return _balance_cache
    except Exception as e:
        print(f"   ⚠️ Balance fetch error: {e}")
        return None


def compute_position_sizing():
    """Returns (trade_amount_dollars, max_position_dollars) based on current bankroll.
    Falls back to safe defaults if balance can't be fetched."""
    balance_cents = get_kalshi_balance_cents()
    if balance_cents is None or balance_cents == 0:
        return FALLBACK_TRADE_AMOUNT_DOLLARS, FALLBACK_MAX_POSITION_DOLLARS
    bankroll = balance_cents / 100.0
    trade_amt = max(MIN_TRADE_AMOUNT_DOLLARS,
                    min(MAX_TRADE_AMOUNT_DOLLARS, bankroll * TRADE_AMOUNT_PCT / 100.0))
    max_pos = max(trade_amt, bankroll * MAX_POSITION_PCT / 100.0)
    return trade_amt, max_pos


# =============================================================================
# ODDS API (existing + cache helpers)
# =============================================================================

def american_to_prob(american_odds):
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def _load_odds_cache_from_disk():
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
    global _odds_cache
    if _odds_cache is not None:
        return _odds_cache

    disk = _load_odds_cache_from_disk()
    if disk is not None:
        _odds_cache = disk
        print(f"📊 Using cached odds for {len(disk)} games (age < {ODDS_CACHE_TTL_SECONDS//60} min)")
        return _odds_cache

    api_key = os.getenv('ODDS_API_KEY')
    if not api_key:
        print("⚠️ ODDS_API_KEY not set — bot will not enter NEW positions this run.")
        _odds_cache = []
        return _odds_cache

    url = f"{ODDS_API_BASE}/sports/{ODDS_API_SPORT}/odds"
    params = {'apiKey': api_key, 'regions': ODDS_API_REGION, 'markets': 'h2h', 'oddsFormat': 'american'}
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
            home_probs, away_probs = [], []
            for bm in g.get('bookmakers', []):
                for market in bm.get('markets', []):
                    if market.get('key') != 'h2h':
                        continue
                    outcomes = {o['name']: o['price'] for o in market.get('outcomes', [])}
                    if home in outcomes and away in outcomes:
                        h = american_to_prob(outcomes[home])
                        a = american_to_prob(outcomes[away])
                        total = h + a
                        if total > 0:
                            home_probs.append(h / total)
                            away_probs.append(a / total)
            if home_probs:
                processed.append({
                    'home': home, 'away': away,
                    'commence_time': g.get('commence_time'),
                    'fair_home_prob': sum(home_probs) / len(home_probs),
                    'fair_away_prob': sum(away_probs) / len(away_probs),
                    'num_books': len(home_probs),
                })

        _odds_cache = processed
        _write_odds_cache_to_disk(processed)
        used = resp.headers.get('x-requests-used', '?')
        remaining = resp.headers.get('x-requests-remaining', '?')
        print(f"📊 Loaded de-juiced odds for {len(processed)} MLB games (fresh)")
        print(f"   Odds API usage: {used} used, {remaining} remaining this month")
        return _odds_cache
    except Exception as e:
        print(f"⚠️ Odds API fetch error: {e}")
        _odds_cache = []
        return _odds_cache


def get_fair_yes_prob(ticker, odds_data):
    parts = ticker.split('-')
    if len(parts) < 2:
        return None
    team_abbrev = parts[-1]
    team_name = KALSHI_TO_ODDS_TEAM.get(team_abbrev)
    if not team_name:
        return None
    for game in odds_data:
        if game['home'] == team_name:
            return game['fair_home_prob']
        if game['away'] == team_name:
            return game['fair_away_prob']
    return None


# =============================================================================
# PITCHER CHECK (NEW)
# =============================================================================

_mlb_schedule_cache = None

def fetch_today_mlb_schedule():
    """Pull today's MLB schedule with probable pitchers. Cached per run."""
    global _mlb_schedule_cache
    if _mlb_schedule_cache is not None:
        return _mlb_schedule_cache
    today = datetime.date.today().strftime("%Y-%m-%d")
    try:
        url = f"{MLB_STATS_API}/schedule"
        params = {"sportId": 1, "date": today, "hydrate": "probablePitcher"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"   ⚠️ MLB Stats API HTTP {resp.status_code}")
            _mlb_schedule_cache = []
            return _mlb_schedule_cache
        dates = resp.json().get('dates', [])
        games = []
        for d in dates:
            for g in d.get('games', []):
                games.append({
                    'game_pk': g.get('gamePk'),
                    'status': g.get('status', {}).get('abstractGameState', ''),
                    'detailed_status': g.get('status', {}).get('detailedState', ''),
                    'home_id': g.get('teams', {}).get('home', {}).get('team', {}).get('id'),
                    'away_id': g.get('teams', {}).get('away', {}).get('team', {}).get('id'),
                    'home_pitcher': (g.get('teams', {}).get('home', {})
                                     .get('probablePitcher') or {}).get('fullName'),
                    'away_pitcher': (g.get('teams', {}).get('away', {})
                                     .get('probablePitcher') or {}).get('fullName'),
                })
        _mlb_schedule_cache = games
        print(f"⚾ MLB schedule: {len(games)} games today")
        return _mlb_schedule_cache
    except Exception as e:
        print(f"   ⚠️ MLB Stats API error: {e}")
        _mlb_schedule_cache = []
        return _mlb_schedule_cache


def check_pitcher_status(team_abbrev):
    """Returns (ok, reason). ok=True means safe to trade.
    ok=False with reason means skip (e.g., 'pitcher TBD', 'game postponed')."""
    if not USE_PITCHER_CHECK:
        return True, ""
    team_id = KALSHI_TO_MLB_TEAM_ID.get(team_abbrev)
    if not team_id:
        return True, ""
    schedule = fetch_today_mlb_schedule()
    if not schedule:
        return True, ""
    for game in schedule:
        if game['home_id'] == team_id or game['away_id'] == team_id:
            detailed = game.get('detailed_status', '').lower()
            if any(x in detailed for x in ['postponed', 'cancelled', 'suspended']):
                return False, f"game {game['detailed_status']}"
            home_p = game.get('home_pitcher')
            away_p = game.get('away_pitcher')
            if not home_p or not away_p:
                return False, "probable pitcher TBD (line not fully solidified)"
            return True, ""
    return True, ""


# =============================================================================
# WEATHER CHECK (NEW)
# =============================================================================

_weather_cache = {}

def check_weather_risk(team_abbrev):
    """Returns (ok, reason). ok=False means skip due to high rain probability.
    Only checks the home team's stadium. Fail open on any error."""
    if not USE_WEATHER_CHECK:
        return True, ""
    coords = STADIUM_COORDS.get(team_abbrev)
    if not coords:
        return True, ""
    cache_key = team_abbrev
    if cache_key in _weather_cache:
        return _weather_cache[cache_key]
    lat, lon = coords
    try:
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "precipitation_probability",
            "forecast_days": 1, "timezone": "auto",
        }
        resp = requests.get(WEATHER_API, params=params, timeout=10)
        if resp.status_code != 200:
            result = (True, "")
            _weather_cache[cache_key] = result
            return result
        data = resp.json()
        probs = data.get('hourly', {}).get('precipitation_probability') or []
        if probs:
            game_window = probs[13:23] if len(probs) >= 23 else probs
            max_prob = max(game_window) if game_window else 0
            if max_prob > MAX_RAIN_PROBABILITY:
                result = (False, f"rain probability {max_prob}% at home stadium")
            else:
                result = (True, "")
        else:
            result = (True, "")
        _weather_cache[cache_key] = result
        return result
    except Exception:
        return True, ""


# =============================================================================
# ENTRY PRICE TRACKING (NEW)
# =============================================================================

def load_entry_prices():
    """Returns {ticker: entry_cents} dict. Persists across runs via actions/cache."""
    global _entry_prices
    if _entry_prices is not None:
        return _entry_prices
    try:
        with open(ENTRY_PRICES_PATH, 'r') as f:
            _entry_prices = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _entry_prices = {}
    return _entry_prices


def save_entry_price(ticker, side, price_cents):
    """Record entry price for a position. Side-aware: yes vs no stored separately."""
    prices = load_entry_prices()
    key = f"{ticker}:{side}"
    prices[key] = int(price_cents)
    try:
        with open(ENTRY_PRICES_PATH, 'w') as f:
            json.dump(prices, f)
    except OSError as e:
        print(f"   ⚠️ Could not save entry price: {e}")


def get_entry_price(ticker, side):
    """Returns entry price in cents, or None if not recorded."""
    prices = load_entry_prices()
    return prices.get(f"{ticker}:{side}")


def clear_entry_price(ticker, side):
    """Clear entry price after position closes."""
    prices = load_entry_prices()
    prices.pop(f"{ticker}:{side}", None)
    try:
        with open(ENTRY_PRICES_PATH, 'w') as f:
            json.dump(prices, f)
    except OSError:
        pass


# =============================================================================
# MARKET DEPTH CHECK (NEW in v4)
# =============================================================================

def check_market_depth(ticker, side, ask_cents, bid_cents):
    """Skip thin / wide-spread markets where slippage and noise dominate edge.
    Returns (ok, reason)."""
    if not USE_DEPTH_CHECK:
        return True, ""
    spread = ask_cents - bid_cents
    if spread > MAX_BID_ASK_SPREAD_CENTS:
        return False, f"spread {spread}¢ > {MAX_BID_ASK_SPREAD_CENTS}¢"

    # Check top-of-book size via the orderbook endpoint
    try:
        resp = make_kalshi_request("GET", f"/markets/{ticker}/orderbook")
        if resp is None or resp.status_code != 200:
            return True, ""
        book = resp.json().get('orderbook', {})
        levels = book.get('yes', []) if side == "yes" else book.get('no', [])
        if not levels:
            return False, "empty orderbook on this side"
        for price, size in levels:
            if int(price) == int(ask_cents):
                if size < MIN_TOP_OF_BOOK_SIZE:
                    return False, f"only {size} contracts at {ask_cents}¢"
                return True, ""
        return True, ""
    except Exception as e:
        print(f"   ⚠️ Depth check error: {e} — auto-passing")
        return True, ""


# =============================================================================
# TRADE LOGGING (NEW in v4)
# =============================================================================

TRADE_LOG_HEADER = (
    "timestamp,ticker,team,event,side,kalshi_ask,kalshi_bid,fair_yes_cents,"
    "edge_cents,ai_confidence,contracts,price,bankroll,reason\n"
)


def _ensure_trade_log_exists():
    if not os.path.exists(TRADE_LOG_PATH):
        try:
            with open(TRADE_LOG_PATH, 'w') as f:
                f.write(TRADE_LOG_HEADER)
        except OSError as e:
            print(f"   ⚠️ Could not init trade log: {e}")


def log_trade_decision(**kwargs):
    """Append a row to the trade log CSV. Fields are optional — empty string for missing.
    Events: ENTRY, SKIP, HARVEST, STOP_FLOOR, STOP_DYNAMIC, ENTRY_FAIL."""
    if not USE_TRADE_LOGGING:
        return
    _ensure_trade_log_exists()
    fields = ['ticker', 'team', 'event', 'side', 'kalshi_ask', 'kalshi_bid',
              'fair_yes_cents', 'edge_cents', 'ai_confidence', 'contracts',
              'price', 'bankroll', 'reason']
    row = [datetime.datetime.now(datetime.timezone.utc).isoformat()]
    for f in fields:
        v = kwargs.get(f, '')
        s = str(v).replace(',', ';').replace('\n', ' ').replace('"', "'")
        row.append(s)
    try:
        with open(TRADE_LOG_PATH, 'a') as fh:
            fh.write(','.join(row) + '\n')
    except OSError as e:
        print(f"   ⚠️ Could not write to trade log: {e}")


# =============================================================================
# AI CONFIDENCE GATE — ENSEMBLE (Grok + Gemini)
# =============================================================================

def _strip_fences(text):
    """Strip markdown code fences from LLM JSON output."""
    text = text.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text[3:]
        if text.lower().startswith('json'):
            text = text[4:]
        if text.endswith(fence):
            text = text[:-3]
        text = text.strip()
    return text


def _build_ai_prompt(ticker, side, kalshi_price_cents, fair_prob_pct, edge_cents):
    return f"""You are evaluating an MLB prediction-market bet on Kalshi.

TICKER: {ticker}
SIDE: {side.upper()}
KALSHI PRICE: {kalshi_price_cents}¢
DE-JUICED CONSENSUS FAIR PROBABILITY: {fair_prob_pct}¢
DETECTED EDGE: {edge_cents}¢ (Kalshi appears to be mispricing vs sportsbook consensus)

Use general baseball knowledge: starting pitcher matchup, team form, weather/postponement risk, situational factors (travel, rest, day game after night game). The consensus odds already account for most of this, so only deviate if you have specific reason.

Return ONLY a JSON object with keys "confidence" (0.0 to 1.0) and "reason" (one sentence).
No other text, no markdown fences."""


def _grok_confidence(prompt):
    """Returns (confidence, reason) from Grok. Returns (None, '') on any failure."""
    api_key = os.getenv('XAI_API_KEY')
    if not api_key:
        return None, ''
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "grok-3", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 200},
            timeout=15,
        )
        if resp.status_code != 200:
            return None, ''
        text = _strip_fences(resp.json()['choices'][0]['message']['content'])
        data = json.loads(text)
        return float(data.get('confidence', 0.5)), data.get('reason', '')
    except Exception as e:
        print(f"   ⚠️ Grok error: {e}")
        return None, ''


def _gemini_confidence(prompt):
    """Returns (confidence, reason) from Gemini. Returns (None, '') on any failure."""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return None, ''
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 200, "responseMimeType": "application/json"},
        }
        resp = requests.post(url, json=body, timeout=15)
        if resp.status_code != 200:
            return None, ''
        candidates = resp.json().get('candidates', [])
        if not candidates:
            return None, ''
        text = _strip_fences(candidates[0].get('content', {}).get('parts', [{}])[0].get('text', ''))
        data = json.loads(text)
        return float(data.get('confidence', 0.5)), data.get('reason', '')
    except Exception as e:
        print(f"   ⚠️ Gemini error: {e}")
        return None, ''


def ai_confidence_check(ticker, side, kalshi_price_cents, fair_prob_pct, edge_cents):
    """Ensemble of Grok + Gemini. Returns weighted confidence 0-1.
    Returns 1.0 (auto-pass) if AI is disabled or both models fail."""
    ai_confidence_check.last_reason = ""
    if not USE_AI_GATE:
        return 1.0
    prompt = _build_ai_prompt(ticker, side, kalshi_price_cents, fair_prob_pct, edge_cents)

    grok_conf, grok_reason = _grok_confidence(prompt)
    gemini_conf, gemini_reason = _gemini_confidence(prompt)

    confidences = []
    weights = []
    reasons = []
    if grok_conf is not None:
        confidences.append(grok_conf)
        weights.append(GROK_WEIGHT)
        reasons.append(f"Grok {grok_conf:.2f}: {grok_reason}")
    if gemini_conf is not None:
        confidences.append(gemini_conf)
        weights.append(GEMINI_WEIGHT)
        reasons.append(f"Gemini {gemini_conf:.2f}: {gemini_reason}")

    if not confidences:
        print("   ⚠️ Both AI models failed — auto-passing.")
        return 1.0

    total_w = sum(weights)
    weighted = sum(c * w for c, w in zip(confidences, weights)) / total_w
    print(f"   🤖 Ensemble confidence: {weighted:.2f} ({len(confidences)} model(s))")
    for r in reasons:
        print(f"      • {r}")
    ai_confidence_check.last_reason = " | ".join(reasons)
    return weighted


# =============================================================================
# MAIN RUN
# =============================================================================

def run_mlb_auto_hunter():
    print(f"⚾ MLB AUTO-HUNTER WAKING UP: {time.strftime('%X')} UTC")
    if not os.getenv('KALSHI_KEY_ID') or not os.getenv('KALSHI_PRIVATE_KEY'):
        print("❌ Missing Kalshi secrets!")
        return

    odds_data = fetch_mlb_odds()
    trade_amount_dollars, max_position_dollars = compute_position_sizing()
    print(f"💵 Position sizing: ${trade_amount_dollars:.2f}/trade, ${max_position_dollars:.2f}/team cap")
    _bal = get_kalshi_balance_cents()
    balance_for_log = f"{_bal/100:.2f}" if _bal is not None else ""

    print("📡 Scanning Kalshi for active MLB games...")
    markets_resp = make_kalshi_request("GET", "/markets?series_ticker=KXMLBGAME&status=open&limit=100")
    qualifying_tickers = []
    skipped_future, skipped_too_close, skipped_illiquid = 0, 0, 0

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
        print(f"🎯 {len(qualifying_tickers)} qualifying markets (skipped: "
              f"{skipped_future} future, {skipped_too_close} too close, {skipped_illiquid} illiquid)")
    else:
        print("⚠️ Could not fetch Kalshi markets.")
        return

    if not qualifying_tickers:
        print("💤 No qualifying MLB games. Going back to sleep.")
        return

    pos_resp = make_kalshi_request("GET", "/portfolio/positions")
    all_positions = []
    invested_base_games = set()
    if pos_resp and pos_resp.status_code == 200:
        all_positions = pos_resp.json().get('market_positions', [])
        for p in all_positions:
            pos_count = int(float(p.get('position_fp', '0')))
            if pos_count != 0:
                base_game = p.get('ticker', '').rsplit('-', 1)[0]
                invested_base_games.add(base_game)

    for ticker in qualifying_tickers:
        print("")
        print("----------------------------------------")
        print(f"🎯 ANALYZING: {ticker}")

        team_abbrev = ticker.rsplit('-', 1)[-1]
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

        current_yes_contracts = 0
        current_no_contracts = 0
        for p in all_positions:
            if p.get('ticker') == ticker:
                pos = int(float(p.get('position_fp', '0')))
                if pos > 0:
                    current_yes_contracts = pos
                elif pos < 0:
                    current_no_contracts = abs(pos)

        if current_yes_contracts > 0:
            entry = get_entry_price(ticker, 'yes')
            print(f"💰 Hold {current_yes_contracts} YES @ entry {entry or '?'}¢, bid {yes_bid}¢")
            should_sell = False
            event = ""
            reason = ""
            if yes_bid >= HARVEST_PRICE:
                should_sell, event, reason = True, "HARVEST", f"HARVEST at {yes_bid}¢"
            elif 0 < yes_bid <= STOP_LOSS_FLOOR:
                should_sell, event, reason = True, "STOP_FLOOR", f"STOP-LOSS FLOOR at {yes_bid}¢"
            elif entry is not None and yes_bid > 0 and (entry - yes_bid) >= STOP_LOSS_DROP_CENTS:
                should_sell, event, reason = True, "STOP_DYNAMIC", f"DYNAMIC STOP: bid dropped {entry - yes_bid}¢ from {entry}¢ entry"
            if should_sell:
                print(f"   🚨 {reason}")
                ok = _place_limit(ticker, "sell", "yes", current_yes_contracts, yes_bid)
                log_trade_decision(ticker=ticker, team=team_abbrev, event=event,
                                   side="yes", kalshi_bid=yes_bid, contracts=current_yes_contracts,
                                   price=yes_bid, bankroll=balance_for_log, reason=reason)
                if ok:
                    clear_entry_price(ticker, 'yes')
                continue

        if current_no_contracts > 0:
            entry = get_entry_price(ticker, 'no')
            print(f"💰 Hold {current_no_contracts} NO @ entry {entry or '?'}¢, bid {no_bid}¢")
            should_sell = False
            event = ""
            reason = ""
            if no_bid >= HARVEST_PRICE:
                should_sell, event, reason = True, "HARVEST", f"HARVEST at {no_bid}¢"
            elif 0 < no_bid <= STOP_LOSS_FLOOR:
                should_sell, event, reason = True, "STOP_FLOOR", f"STOP-LOSS FLOOR at {no_bid}¢"
            elif entry is not None and no_bid > 0 and (entry - no_bid) >= STOP_LOSS_DROP_CENTS:
                should_sell, event, reason = True, "STOP_DYNAMIC", f"DYNAMIC STOP: bid dropped {entry - no_bid}¢ from {entry}¢ entry"
            if should_sell:
                print(f"   🚨 {reason}")
                ok = _place_limit(ticker, "sell", "no", current_no_contracts, no_bid)
                log_trade_decision(ticker=ticker, team=team_abbrev, event=event,
                                   side="no", kalshi_bid=no_bid, contracts=current_no_contracts,
                                   price=no_bid, bankroll=balance_for_log, reason=reason)
                if ok:
                    clear_entry_price(ticker, 'no')
                continue

        if current_yes_contracts == 0 and current_no_contracts == 0 and current_base_game in invested_base_games:
            print(f"🛑 Skip: already positioned on the other team in this game.")
            continue

        if not odds_data:
            print("⏸️ No odds data — skipping new entries.")
            continue

        ok, reason = check_pitcher_status(team_abbrev)
        if not ok:
            print(f"⏸️ Pitcher/status check failed: {reason}")
            continue

        ok, reason = check_weather_risk(team_abbrev)
        if not ok:
            print(f"⏸️ Weather check failed: {reason}")
            continue

        fair_yes_prob = get_fair_yes_prob(ticker, odds_data)
        if fair_yes_prob is None:
            print(f"⏸️ No de-juiced consensus for {ticker} — skipping.")
            continue
        fair_yes_cents = round(fair_yes_prob * 100)
        fair_no_cents = 100 - fair_yes_cents
        print(f"🧮 Fair value: YES {fair_yes_cents}¢ / NO {fair_no_cents}¢")

        yes_edge = fair_yes_cents - yes_ask
        no_edge = fair_no_cents - no_ask
        chosen_side, chosen_price, chosen_edge = None, None, None
        if yes_edge >= MIN_EDGE_CENTS and MIN_BUY_PRICE <= yes_ask <= MAX_BUY_PRICE:
            if yes_edge > (no_edge if no_edge > 0 else 0):
                chosen_side, chosen_price, chosen_edge = "yes", yes_ask, yes_edge
        if chosen_side is None and no_edge >= MIN_EDGE_CENTS and MIN_BUY_PRICE <= no_ask <= MAX_BUY_PRICE:
            chosen_side, chosen_price, chosen_edge = "no", no_ask, no_edge
        if chosen_side is None:
            print(f"⏳ No edge ≥ {MIN_EDGE_CENTS}¢ in band {MIN_BUY_PRICE}-{MAX_BUY_PRICE}¢. "
                  f"YES edge: {yes_edge:+d}¢, NO edge: {no_edge:+d}¢.")
            continue
        print(f"💡 Edge found: {chosen_side.upper()} at {chosen_price}¢ with +{chosen_edge}¢ edge")

        depth_ok, depth_reason = check_market_depth(ticker, chosen_side, chosen_price,
                                                    yes_bid if chosen_side == "yes" else no_bid)
        if not depth_ok:
            print(f"⏸️ Depth check failed: {depth_reason}")
            log_trade_decision(ticker=ticker, team=team_abbrev, event="SKIP",
                               side=chosen_side, kalshi_ask=chosen_price,
                               kalshi_bid=yes_bid if chosen_side == "yes" else no_bid,
                               fair_yes_cents=fair_yes_cents, edge_cents=chosen_edge,
                               bankroll=balance_for_log, reason=f"depth: {depth_reason}")
            continue

        confidence = ai_confidence_check(
            ticker, chosen_side, chosen_price,
            fair_yes_cents if chosen_side == "yes" else fair_no_cents,
            chosen_edge,
        )
        if confidence < MIN_AI_CONFIDENCE:
            print(f"   ⛔ AI confidence {confidence:.2f} < {MIN_AI_CONFIDENCE} — skipping.")
            log_trade_decision(ticker=ticker, team=team_abbrev, event="SKIP",
                               side=chosen_side, kalshi_ask=chosen_price,
                               kalshi_bid=yes_bid if chosen_side == "yes" else no_bid,
                               fair_yes_cents=fair_yes_cents, edge_cents=chosen_edge,
                               ai_confidence=confidence, bankroll=balance_for_log,
                               reason=f"AI<{MIN_AI_CONFIDENCE}: {ai_confidence_check.last_reason}")
            continue

        existing_dollars = (current_yes_contracts * yes_bid + current_no_contracts * no_bid) / 100
        if existing_dollars >= max_position_dollars:
            print(f"🛡️ Already at max exposure (${existing_dollars:.2f}). Holding.")
            continue
        dollars_room = max_position_dollars - existing_dollars
        target_buy_dollars = min(trade_amount_dollars, dollars_room)
        contracts_to_buy = int((target_buy_dollars * 100) / chosen_price)
        if contracts_to_buy <= 0:
            continue

        print(f"🛒 Buying {contracts_to_buy} {chosen_side.upper()} contracts @ {chosen_price}¢")
        success = _place_limit(ticker, "buy", chosen_side, contracts_to_buy, chosen_price)
        if success:
            invested_base_games.add(current_base_game)
            save_entry_price(ticker, chosen_side, chosen_price)
            log_trade_decision(ticker=ticker, team=team_abbrev, event="ENTRY",
                               side=chosen_side, kalshi_ask=chosen_price,
                               kalshi_bid=yes_bid if chosen_side == "yes" else no_bid,
                               fair_yes_cents=fair_yes_cents, edge_cents=chosen_edge,
                               ai_confidence=confidence, contracts=contracts_to_buy,
                               price=chosen_price, bankroll=balance_for_log,
                               reason="all gates passed")
        else:
            log_trade_decision(ticker=ticker, team=team_abbrev, event="ENTRY_FAIL",
                               side=chosen_side, kalshi_ask=chosen_price,
                               kalshi_bid=yes_bid if chosen_side == "yes" else no_bid,
                               fair_yes_cents=fair_yes_cents, edge_cents=chosen_edge,
                               ai_confidence=confidence, contracts=contracts_to_buy,
                               price=chosen_price, bankroll=balance_for_log,
                               reason="Kalshi order rejected")

        time.sleep(1)


def _place_limit(ticker, action, side, count, price_cents):
    payload = {
        "ticker": ticker, "action": action, "side": side, "count": count,
        "type": "limit", "client_order_id": str(uuid.uuid4()),
    }
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
