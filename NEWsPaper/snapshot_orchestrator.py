import requests
import sqlite3
import time
import schedule
import json
from datetime import datetime, timezone
import yaml
import os
from dotenv import load_dotenv

load_dotenv()
config = yaml.safe_load(open("config.yaml"))
# Inject secrets from environment (not stored in config.yaml)
config["balldontlie_api_key"] = os.getenv("BALLDONTLIE_API_KEY", "")
config["xai_api_key"]         = os.getenv("XAI_API_KEY", "")

DB = "sports_betting.db"
KALSHI_BASE = config["kalshi_base_url"]

COMEBACK_RATES = {6: 0.232, 8: 0.149, 10: 0.111, 12: 0.043, 14: 0.025, 16: 0.027}

# -- Caches -------------------------------------------------------------------
# Each source has its own TTL matching how fast that data actually changes.
# The snapshot loop runs every 5 min for live alerts, but only hits external
# APIs when their individual TTL has expired.
_pp_cache     = {"data": None, "fetched_at": 0}
_kalshi_cache = {"data": None, "fetched_at": 0}
_bdl_cache    = {"data": None, "fetched_at": 0}

PP_CACHE_TTL     = 3600  # PrizePicks lines: 1 hour  (~3 API calls/hr instead of 36)
KALSHI_CACHE_TTL = 1800  # Kalshi futures:   30 min  (slow-moving championship odds)
BDL_CACHE_TTL    = 300   # Live game scores: 5 min   (needed for blowout alert engine)

# Leagues active right now by calendar month (skip rest to avoid 429s)
ACTIVE_LEAGUES_BY_MONTH = {
    1:  ["NBA", "NHL", "NFL"],
    2:  ["NBA", "NHL", "NFL"],
    3:  ["NBA", "NHL", "MLB"],   # MLB Opening Day is late March
    4:  ["NBA", "NHL", "MLB"],
    5:  ["NBA", "NHL", "MLB"],
    6:  ["NBA", "MLB"],
    7:  ["MLB"],
    8:  ["MLB", "NFL"],
    9:  ["MLB", "NFL", "NBA"],
    10: ["NBA", "NHL", "MLB", "NFL"],
    11: ["NBA", "NHL", "NFL"],
    12: ["NBA", "NHL", "NFL"],
}
LEAGUE_IDS = {"NBA": 7, "NHL": 8, "MLB": 2, "NFL": 9}


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots (
        timestamp TEXT PRIMARY KEY,
        view_level TEXT,
        filter_json TEXT,
        raw_data TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS best_bets (
        timestamp TEXT, view_level TEXT, filter_json TEXT, bets_json TEXT
    )''')
    # Per-sport PrizePicks cache — survives orchestrator restarts
    c.execute('''CREATE TABLE IF NOT EXISTS pp_cache (
        sport TEXT PRIMARY KEY,
        data TEXT,
        fetched_at REAL
    )''')
    conn.commit()
    conn.close()


def _save_pp_sport(sport, props_list):
    """Persist a successful sport fetch to SQLite so restarts don't lose it."""
    try:
        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT OR REPLACE INTO pp_cache VALUES (?, ?, ?)",
            (sport, json.dumps(props_list), time.time())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] pp_cache write {sport}: {e}")


def _load_pp_sport(sport):
    """Load last-good per-sport props from SQLite. Returns (props_list, fetched_at) or (None, 0)."""
    try:
        conn = sqlite3.connect(DB)
        row = conn.execute(
            "SELECT data, fetched_at FROM pp_cache WHERE sport=?", (sport,)
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row[0]), row[1]
    except Exception as e:
        print(f"[WARN] pp_cache read {sport}: {e}")
    return None, 0


# -- Kalshi -------------------------------------------------------------------

_KALSHI_MONTHS = {
    "JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
    "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12
}

def _parse_game_date(ticker):
    """Extract UTC date from a Kalshi game ticker like KXNBAGAME-26MAR31CLELAL-LAL."""
    import re
    m = re.search(r"-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})", ticker)
    if m:
        from datetime import datetime, timezone
        return datetime(2000 + int(m.group(1)), _KALSHI_MONTHS[m.group(2)], int(m.group(3)), tzinfo=timezone.utc)
    return None


def fetch_kalshi_markets():
    """
    Fetches two layers:
      - Game markets (KXNBAGAME/KXNHLGAME/KXMLBGAME): filtered to next 48h window
      - Futures  (KXNBA/KXNHL/KXMLB): championship odds, volume > 0
    Returns a combined list tagged with _market_type = 'game' | 'futures'.
    Cached 20 min.
    """
    global _kalshi_cache
    now_ts = time.time()
    if _kalshi_cache["data"] is not None and now_ts - _kalshi_cache["fetched_at"] < KALSHI_CACHE_TTL:
        age = int((now_ts - _kalshi_cache["fetched_at"]) / 60)
        print(f"[INFO] Kalshi cache hit ({len(_kalshi_cache['data'])} markets, age {age}m)")
        return _kalshi_cache["data"]

    from datetime import datetime, timezone, timedelta
    now_dt  = datetime.now(timezone.utc)
    cutoff  = now_dt + timedelta(hours=48)
    lookback = now_dt - timedelta(hours=6)   # include live/recently-started games

    all_markets = []

    # ── Game markets (48h window, any volume) ────────────────────────────────
    for series in ["KXNBAGAME", "KXNHLGAME", "KXMLBGAME"]:
        sport = series.replace("KX","").replace("GAME","")   # NBA / NHL / MLB
        try:
            r = requests.get(
                f"{KALSHI_BASE}/markets",
                params={"status": "open", "limit": 200, "series_ticker": series},
                timeout=10
            )
            if r.status_code == 200:
                markets = r.json().get("markets", [])
                kept = []
                for m in markets:
                    gd = _parse_game_date(m["ticker"])
                    if gd and lookback <= gd <= cutoff:
                        m["_series"]      = series
                        m["_market_type"] = "game"
                        m["_sport"]       = sport
                        m["_game_date"]   = gd.strftime("%b %d")
                        kept.append(m)
                all_markets.extend(kept)
                print(f"[OK] Kalshi {series}: {len(kept)}/{len(markets)} in 48h window")
            else:
                print(f"[WARN] Kalshi {series} returned {r.status_code}")
        except Exception as e:
            print(f"[WARN] Kalshi {series} error: {e}")
        time.sleep(0.3)

    # ── Futures (championship odds, volume > 0) ───────────────────────────────
    for series in ["KXNBA", "KXNHL", "KXMLB"]:
        sport = series.replace("KX","")
        try:
            r = requests.get(
                f"{KALSHI_BASE}/markets",
                params={"status": "open", "limit": 200, "series_ticker": series},
                timeout=10
            )
            if r.status_code == 200:
                markets = r.json().get("markets", [])
                liquid = []
                for m in markets:
                    if float(m.get("volume_24h_fp") or 0) > 0:
                        m["_series"]      = series
                        m["_market_type"] = "futures"
                        m["_sport"]       = sport
                        liquid.append(m)
                all_markets.extend(liquid)
                print(f"[OK] Kalshi {series} futures: {len(liquid)}/{len(markets)} liquid")
            else:
                print(f"[WARN] Kalshi {series} returned {r.status_code}")
        except Exception as e:
            print(f"[WARN] Kalshi {series} error: {e}")
        time.sleep(0.3)

    if all_markets:
        _kalshi_cache = {"data": all_markets, "fetched_at": now_ts}
    return all_markets


# -- PrizePicks ---------------------------------------------------------------

def _annotate_props(props, included, sport):
    """Annotate props list in-place with _sport/_player/_team/_team_display."""
    player_lookup = {}
    for item in included:
        if item.get("type") != "new_player":
            continue
        attrs = item.get("attributes", {})
        player_lookup[item["id"]] = {
            "name":      attrs.get("display_name", ""),
            "team":      attrs.get("team", ""),
            "team_name": attrs.get("team_name", ""),
            "market":    attrs.get("market", ""),
            "position":  attrs.get("position", ""),
        }
    for p in props:
        if not isinstance(p, dict):
            continue
        p["_sport"] = sport
        player_rel = (p.get("relationships") or {}).get("new_player", {})
        player_id  = (player_rel.get("data") or {}).get("id")
        info       = player_lookup.get(player_id, {})
        p["_player"]       = info.get("name") or p.get("attributes", {}).get("description", "")
        p["_team"]         = info.get("team", "")
        p["_team_name"]    = f"{info.get('market','')} {info.get('team_name','')}".strip()
        p["_team_display"] = p["_team_name"] or p.get("attributes", {}).get("description", "")


def fetch_prizepicks_props():
    """
    Fetch PrizePicks projections.  Each sport is cached independently (both
    in-memory and SQLite) so a restart or a 429 on one sport never wipes the
    others.  Falls back to last-good SQLite data when the API fails.
    """
    global _pp_cache
    now = time.time()

    # Fast path: combined in-memory cache still fresh
    if _pp_cache["data"] is not None and now - _pp_cache["fetched_at"] < PP_CACHE_TTL:
        cached = _pp_cache["data"]
        print(f"[INFO] PrizePicks cache hit ({cached['total']} props, age {int(now - _pp_cache['fetched_at'])}s)")
        return cached

    month   = datetime.now().month
    active  = ACTIVE_LEAGUES_BY_MONTH.get(month, ["NBA", "NHL"])
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    # Per-sport in-memory sub-caches so we only hit fresh ones
    if not hasattr(fetch_prizepicks_props, "_sport_cache"):
        fetch_prizepicks_props._sport_cache = {}

    all_props  = []
    first_fetch = True  # no sleep before the first sport

    for sport in active:
        sport_cache = fetch_prizepicks_props._sport_cache.get(sport, {"data": None, "fetched_at": 0})

        # Sport sub-cache still fresh — skip API call
        if sport_cache["data"] is not None and now - sport_cache["fetched_at"] < PP_CACHE_TTL:
            age_m = int((now - sport_cache["fetched_at"]) / 60)
            print(f"[INFO] {sport}: sub-cache hit ({len(sport_cache['data'])} props, age {age_m}m)")
            all_props.extend(sport_cache["data"])
            continue

        if not first_fetch:
            time.sleep(10)  # 10s between league fetches — well under rate limits
        first_fetch = False

        league_id = LEAGUE_IDS[sport]
        fetched_props = None

        for attempt in range(2):
            try:
                resp = requests.get(
                    f"{config['prizepicks_base']}/projections",
                    params={"league_id": league_id, "per_page": 500, "single_stat": "true"},
                    headers=headers,
                    timeout=15
                )
                if resp.status_code == 200:
                    body     = resp.json()
                    props    = [p for p in body.get("data", []) if isinstance(p, dict)]
                    included = body.get("included", [])
                    _annotate_props(props, included, sport)
                    fetched_props = props
                    print(f"[OK] {sport}: {len(props)} props")
                    break

                elif resp.status_code == 429:
                    if attempt == 0:
                        print(f"[WARN] PrizePicks {sport} rate-limited — waiting 60s before retry...")
                        time.sleep(60)
                    else:
                        print(f"[WARN] PrizePicks {sport} rate-limited after retry — using fallback")
                else:
                    print(f"[WARN] PrizePicks {sport} returned {resp.status_code}")
                    break

            except Exception as e:
                print(f"[WARN] PrizePicks {sport} error: {e}")
                break

        if fetched_props is not None and len(fetched_props) > 0:
            # Update both in-memory sub-cache and SQLite
            fetch_prizepicks_props._sport_cache[sport] = {"data": fetched_props, "fetched_at": now}
            _save_pp_sport(sport, fetched_props)
            all_props.extend(fetched_props)
        else:
            # Fallback: load last-good data from SQLite
            db_props, db_ts = _load_pp_sport(sport)
            if db_props:
                age_h = int((now - db_ts) / 3600)
                print(f"[INFO] {sport}: using SQLite fallback ({len(db_props)} props, age ~{age_h}h)")
                fetch_prizepicks_props._sport_cache[sport] = {"data": db_props, "fetched_at": db_ts}
                all_props.extend(db_props)
            else:
                print(f"[WARN] {sport}: no props and no SQLite fallback available")

    result = {
        "props": all_props,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(all_props)
    }
    print(f"[INFO] PrizePicks total: {len(all_props)} props")
    if all_props:
        _pp_cache = {"data": result, "fetched_at": now}
    return result


# -- BallDontLie --------------------------------------------------------------

def fetch_sports_data():
    global _bdl_cache
    now = time.time()
    if _bdl_cache["data"] is not None and now - _bdl_cache["fetched_at"] < BDL_CACHE_TTL:
        print(f"[INFO] BallDontLie cache hit (age {int(now - _bdl_cache['fetched_at'])}s)")
        return _bdl_cache["data"]
    try:
        headers = {"Authorization": f"Bearer {config['balldontlie_api_key']}"}
        resp = requests.get(
            "https://api.balldontlie.io/v1/games",
            params={"per_page": 100, "seasons[]": 2025},
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            data = {"games": resp.json().get("data", []), "lineups": [], "injuries": []}
            _bdl_cache = {"data": data, "fetched_at": now}
            return data
        print(f"[WARN] BallDontLie returned {resp.status_code}")
    except Exception as e:
        print(f"[WARN] BallDontLie error: {e}")
    # Return last cached value if available, else empty
    return _bdl_cache["data"] or {"games": [], "lineups": [], "injuries": []}


# -- Alert engine -------------------------------------------------------------

def is_game_effectively_over(game):
    if not game or game.get("status") == "Final":
        return None
    period = game.get("period", 0)
    if period != 4 and str(period).upper() != "OT":
        return None
    time_str = game.get("time") or "12:00"
    try:
        parts = time_str.split(":")
        time_left = int(parts[0]) * 60 + int(parts[1])
    except Exception:
        time_left = 720
    if time_left > 720:
        return None
    home_score = game.get("home_team_score") or 0
    away_score = game.get("visitor_team_score") or 0
    diff = abs(home_score - away_score)
    if time_left <= 120 and diff >= 12:
        comeback_prob = 0.01
    else:
        comeback_prob = COMEBACK_RATES.get(diff, 0.01) * (time_left / 720.0)
    if comeback_prob < 0.02:
        leader = "home" if home_score > away_score else "away"
        home_name = (game.get("home_team") or {}).get("full_name", "Home")
        away_name = (game.get("visitor_team") or {}).get("full_name", "Away")
        return {
            "game_id": game.get("id"),
            "matchup": f"{home_name} vs {away_name}",
            "score": f"{home_score}-{away_score}",
            "time_left": time_left,
            "locked_side": leader,
            "comeback_prob": round(comeback_prob * 100, 2),
            "free_money_ml": f"Bet {leader.upper()} ML at ANY price better than -5000 (near 100% EV)"
        }
    return None


# -- Snapshot -----------------------------------------------------------------

def take_snapshot(view_level="home", filter_dict=None):
    filter_json = json.dumps(filter_dict or {})
    raw = {
        "kalshi": fetch_kalshi_markets(),
        "prizepicks": fetch_prizepicks_props(),
        "sports_data": fetch_sports_data(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    raw["alerts"] = []
    for game in raw["sports_data"].get("games", []):
        alert = is_game_effectively_over(game)
        if alert:
            raw["alerts"].append(alert)
            print(f"[ALERT] {alert['matchup']} effectively over!")

    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
        (raw["timestamp"], view_level, filter_json, json.dumps(raw))
    )
    conn.commit()
    conn.close()
    print(f"[OK] Snapshot saved at {raw['timestamp']}")


def run_orchestrator():
    init_db()
    take_snapshot("home")
    schedule.every(config.get("refresh_interval_seconds", 30)).seconds.do(take_snapshot, "home")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_orchestrator()
