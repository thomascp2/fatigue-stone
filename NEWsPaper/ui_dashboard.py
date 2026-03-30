import streamlit as st
import sqlite3
import json
import re
import pandas as pd
from datetime import datetime, timezone, timedelta
import yaml
from openai import OpenAI

import os
from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="Living Newspaper", layout="wide", page_icon="📡")
config = yaml.safe_load(open("config.yaml"))
config["xai_api_key"] = os.getenv("XAI_API_KEY", "")
client = OpenAI(api_key=config["xai_api_key"], base_url="https://api.x.ai/v1")
DB = "sports_betting.db"

SPORT_LABELS = {"NBA": "Basketball", "NHL": "Hockey", "MLB": "Baseball"}

# ── Dark terminal theme ───────────────────────────────────────────────────────
st.markdown("""
<style>
  html, body, [data-testid="stAppViewContainer"] {
    background-color: #0A0A0A !important;
    color: #E0E0E0 !important;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
  }
  #MainMenu, footer, [data-testid="stToolbar"] { display: none !important; }
  [data-testid="stHeader"] {
    background: linear-gradient(90deg, #0A0A0A 0%, #0f1117 100%) !important;
    border-bottom: 1px solid rgba(0,212,255,0.2) !important;
  }
  [data-testid="stSidebar"] {
    background-color: #0f0f0f !important;
    border-right: 1px solid rgba(0,212,255,0.15) !important;
  }
  [data-testid="stSidebar"] * { color: #C0C0C0 !important; }
  [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: #00D4FF !important; letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.75rem !important;
  }
  h2 {
    color: #E0E0E0 !important; font-size: 1.0rem !important;
    letter-spacing: 0.1em; text-transform: uppercase;
    border-bottom: 1px solid rgba(0,212,255,0.2); padding-bottom: 0.4rem; margin-bottom: 0.8rem;
  }
  [data-testid="stTabs"] [role="tablist"] {
    background: #111 !important; border-bottom: 1px solid rgba(0,212,255,0.2) !important;
  }
  [data-testid="stTabs"] [role="tab"] {
    color: #555 !important; font-size: 0.78rem !important;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 0.6rem 1.4rem !important; border-radius: 0 !important;
    border-bottom: 2px solid transparent !important;
  }
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #00D4FF !important; border-bottom: 2px solid #00D4FF !important; background: transparent !important;
  }
  [data-testid="stMetric"] {
    background: #111 !important; border: 1px solid rgba(0,212,255,0.15) !important;
    border-radius: 6px !important; padding: 1rem 1.2rem !important;
  }
  [data-testid="stMetricLabel"] { color: #555 !important; font-size: 0.7rem !important; text-transform: uppercase; letter-spacing: 0.1em; }
  [data-testid="stMetricValue"] { color: #00D4FF !important; font-size: 1.6rem !important; font-weight: 700; }
  [data-testid="stDataFrame"] { border: 1px solid rgba(0,212,255,0.1) !important; border-radius: 6px !important; }
  [data-testid="stDataFrame"] th {
    background: #111 !important; color: #00D4FF !important;
    font-size: 0.7rem !important; text-transform: uppercase; letter-spacing: 0.08em;
  }
  [data-testid="stDataFrame"] td { background: #0f0f0f !important; color: #D0D0D0 !important; font-size: 0.82rem !important; }
  [data-testid="stDataFrame"] tr:hover td { background: #1a1a2e !important; }
  [data-testid="stButton"] button {
    background: transparent !important; border: 1px solid #00D4FF !important;
    color: #00D4FF !important; border-radius: 4px !important;
    font-family: monospace !important; font-size: 0.8rem !important;
    letter-spacing: 0.08em; text-transform: uppercase; padding: 0.5rem 1.5rem !important;
  }
  [data-testid="stButton"] button:hover {
    background: rgba(0,212,255,0.1) !important; box-shadow: 0 0 12px rgba(0,212,255,0.3);
  }
  /* Wide insight button: full-width, compact height, bright accent */
  div[data-testid="stButton"].enrich-btn button {
    width: 100% !important;
    height: 2.4rem !important;
    padding: 0 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.14em;
    font-weight: 700;
    background: rgba(0,212,255,0.06) !important;
    border: 1px solid #00D4FF !important;
    box-shadow: 0 0 8px rgba(0,212,255,0.15);
    text-align: center !important;
    justify-content: center !important;
    display: flex !important;
    align-items: center !important;
  }
  div[data-testid="stButton"].enrich-btn button:hover {
    background: rgba(0,212,255,0.15) !important;
    box-shadow: 0 0 18px rgba(0,212,255,0.35) !important;
  }
  [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {
    background: #111 !important; border: 1px solid rgba(0,212,255,0.2) !important;
    color: #E0E0E0 !important; border-radius: 4px !important; font-family: monospace !important;
  }
  [data-testid="stAlert"] {
    border-radius: 4px !important; border-left: 3px solid #FF4444 !important;
    background: rgba(255,68,68,0.08) !important;
  }
  [data-testid="stCaptionContainer"] { color: #444 !important; font-size: 0.7rem !important; }
  hr { border-color: rgba(0,212,255,0.1) !important; }
</style>
""", unsafe_allow_html=True)


# ── Data ─────────────────────────────────────────────────────────────────────

def get_latest_snapshot():
    try:
        conn = sqlite3.connect(DB)
        row = conn.execute(
            "SELECT raw_data, timestamp FROM snapshots WHERE view_level='home' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            d = json.loads(row[0])
            d["_db_ts"] = row[1]
            return d
    except Exception as e:
        st.warning(f"DB read error: {e}")
    return None


# ── Filters ──────────────────────────────────────────────────────────────────

def apply_time_filter(props, window_h):
    if window_h == 0:
        return props
    now    = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=window_h)
    out = []
    for p in props:
        a = p.get("attributes", {})
        if a.get("is_live"):
            out.append(p); continue
        raw = a.get("start_time", "")
        if not raw:
            continue
        try:
            st_dt = datetime.fromisoformat(raw)
            if now - timedelta(hours=1) <= st_dt <= cutoff:
                out.append(p)
        except Exception:
            pass
    return out


# ── Props DataFrame ───────────────────────────────────────────────────────────

def build_props_df(props, enrichment=None):
    """
    Columns: player | team | stat | line | flash | PP picks | start
    If enrichment dict provided, adds: szn avg | L5 avg | edge | signal | insight
    """
    rows = []
    for p in props:
        a    = p.get("attributes", {})
        line = a.get("line_score")
        flash = a.get("flash_sale_line_score")
        key  = f"{p.get('_player','')}/{a.get('stat_type','')}"

        row = {
            "player":   p.get("_player", ""),
            "team":     p.get("_team_display", p.get("_team", "")),
            "stat":     a.get("stat_display_name") or a.get("stat_type") or "",
            "line":     line,
            "flash":    flash if flash and flash != line else "",
            "PP picks": a.get("trending_count") or 0,
            "start":    (a.get("start_time") or "")[:16].replace("T", " "),
        }

        if enrichment and key in enrichment:
            e = enrichment[key]
            edge = e.get("edge")
            signal = e.get("signal", "")
            row["szn avg"] = e.get("season_avg", "")
            row["L5 avg"]  = e.get("last_5_avg", "")
            row["edge"]    = f"{'+' if edge and edge > 0 else ''}{edge:.1f}" if isinstance(edge, (int, float)) else ""
            row["signal"]  = signal
            row["insight"] = e.get("context", "")

        rows.append(row)

    if enrichment:
        rows.sort(key=lambda r: abs(float(r.get("edge", 0) or 0)), reverse=True)
    else:
        rows.sort(key=lambda r: r["PP picks"], reverse=True)

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    # Drop columns that are all empty
    if not df.empty:
        df = df.loc[:, (df.astype(str) != "").any(axis=0)]
    return df


# ── Kalshi DataFrames ─────────────────────────────────────────────────────────

def kalshi_games_df(markets):
    """
    Pairs the two team markets for each game into a single row.
    Columns: date | sport | game | fav | fav% | dog | dog% | vig | vol
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for m in markets:
        if m.get("_market_type") == "game":
            buckets[m.get("event_ticker", m["ticker"])].append(m)

    rows = []
    for _, pair in buckets.items():
        pair.sort(key=lambda m: float(m.get("yes_ask_dollars") or 0), reverse=True)
        fav = pair[0]
        dog = pair[1] if len(pair) > 1 else pair[0]
        fav_pct = float(fav.get("yes_ask_dollars") or 0) * 100
        dog_pct = float(dog.get("yes_ask_dollars") or 0) * 100
        total_vol = sum(float(m.get("volume_24h_fp") or 0) for m in pair)
        rows.append({
            "date":  fav.get("_game_date", ""),
            "sport": fav.get("_sport", ""),
            "game":  fav.get("title", "").replace(" Winner?", ""),
            "fav":   fav.get("yes_sub_title", ""),
            "fav %": f"{fav_pct:.0f}%",
            "dog":   dog.get("yes_sub_title", ""),
            "dog %": f"{dog_pct:.0f}%",
            "vig":   f"{fav_pct + dog_pct - 100:.1f}%",
            "vol":   int(total_vol),
        })
    rows.sort(key=lambda r: (r["date"], -r["vol"]))
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["date","sport","game","fav","fav %","dog","dog %","vig","vol"]
    )


def kalshi_futures_df(markets):
    rows = []
    for m in markets:
        if m.get("_market_type") != "futures":
            continue
        yes_ask = float(m.get("yes_ask_dollars") or 0)
        yes_bid = float(m.get("yes_bid_dollars") or 0)
        rows.append({
            "market":  m.get("title", ""),
            "sport":   m.get("_sport", ""),
            "yes ask": f"${yes_ask:.2f}",
            "yes bid": f"${yes_bid:.2f}" if yes_bid else "—",
            "spread":  f"${yes_ask - yes_bid:.2f}" if yes_ask and yes_bid else "—",
            "vol 24h": int(float(m.get("volume_24h_fp") or 0)),
        })
    rows.sort(key=lambda r: -r["vol 24h"])
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["market","sport","yes ask","yes bid","spread","vol 24h"]
    )


# ── Grok: EV enrichment ───────────────────────────────────────────────────────

def parse_json_response(text):
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Try array first, then object
    for delims in [("[", "]"), ("{", "}")]:
        s, e = text.find(delims[0]), text.rfind(delims[1])
        if s != -1 and e != -1:
            return json.loads(text[s:e + 1])
    raise ValueError("No JSON found")


def enrich_with_grok(props):
    """
    Send filtered props to Grok. Returns dict keyed by 'player/stat_type'
    with keys: season_avg, last_5_avg, edge, signal, context.
    """
    items = []
    seen  = set()
    for p in props:
        a   = p.get("attributes", {})
        key = f"{p.get('_player', '')}/{a.get('stat_type', '')}"
        if key in seen or not p.get("_player"):
            continue
        seen.add(key)
        items.append({
            "player": p.get("_player", ""),
            "sport":  p.get("_sport", ""),
            "team":   p.get("_team_display", ""),
            "stat":   a.get("stat_type", ""),
            "line":   a.get("line_score"),
        })

    if not items:
        return {}

    prompt = f"""You are a sports analytics expert with knowledge of current 2024-25 season stats.

For each prop below, return:
- season_avg: the player's 2024-25 season average for that exact stat (or combined stat)
- last_5_avg: average over their last 5 games
- edge: season_avg minus the line (positive = lean OVER, negative = lean UNDER)
- signal: "OVER", "UNDER", or "PUSH" (PUSH if edge within 0.5)
- context: one sentence explaining the edge — mention season avg, recent form, opponent if relevant

Return ONLY a raw JSON array (no markdown, no code fences):
[{{"player":"...", "stat":"...", "line":0, "season_avg":0.0, "last_5_avg":0.0, "edge":0.0, "signal":"...", "context":"..."}}]

Props:
{json.dumps(items, indent=2)}
"""
    try:
        resp = client.chat.completions.create(
            model=config["grok_model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=3000
        )
        enriched = parse_json_response(resp.choices[0].message.content)
        if isinstance(enriched, list):
            return {f"{e['player']}/{e['stat']}": e for e in enriched if "player" in e and "stat" in e}
        return {}
    except Exception as ex:
        return {"_error": str(ex)}


# ── Grok: full analysis ───────────────────────────────────────────────────────

def grok_full_analysis(props, kalshi, focus_label):
    top_props = sorted(props, key=lambda p: p.get("attributes", {}).get("trending_count") or 0, reverse=True)[:50]
    payload   = {"props": top_props, "kalshi": kalshi[:30]}
    prompt    = f"""You are an elite real-time sports-betting analyst.
For EVERY prop/market in the payload:
- True probability, no-vig fair American line, +EV threshold, edge %.
- Implied-Probability Table. Historical Hit Rates. Factor live score, injuries, pace, splits.
- End with "Bottom line" bullets: exact prices to target.
- Set alert_flag true if any game is effectively over.

Return ONLY a raw JSON object (no markdown):
{{"analysis_title":"...","true_prob":0,"fair_line":"...","ev_threshold":"...","edge_at_best_price":"...",
"implied_prob_table":[{{"price":"...","implied":0.0,"edge":"..."}}],
"historical_hit_rate":"...","detailed_breakdown":["..."],"live_context":"...","bottom_line":["..."],"alert_flag":false}}

Focus: {focus_label}
Payload: {json.dumps(payload)[:60000]}
"""
    try:
        resp = client.chat.completions.create(
            model=config["grok_model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=1500
        )
        return parse_json_response(resp.choices[0].message.content)
    except Exception as ex:
        return {"error": str(ex)}


# ── Load data ─────────────────────────────────────────────────────────────────

data = get_latest_snapshot()
if not data:
    st.error("No snapshot. Start: `python snapshot_orchestrator.py`")
    st.stop()

all_props  = data.get("prizepicks", {}).get("props", [])
all_kalshi = data.get("kalshi", [])
all_games  = data.get("sports_data", {}).get("games", [])

if "enrichment_cache" not in st.session_state:
    st.session_state["enrichment_cache"] = {}


# ── Sidebar — filters only ────────────────────────────────────────────────────

st.sidebar.markdown(
    "<div style='font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;"
    "color:#00D4FF;padding-bottom:0.5rem;border-bottom:1px solid rgba(0,212,255,0.2);'>"
    "Filter Panel</div>", unsafe_allow_html=True
)

sport_options     = sorted({p.get("_sport") for p in all_props if p.get("_sport")})
sport_labels_map  = {f"{SPORT_LABELS.get(s,s)} ({s})": s for s in sport_options}
sport_label_sel   = st.sidebar.radio("Sport", ["All"] + list(sport_labels_map.keys()))
sport_sel         = None if sport_label_sel == "All" else sport_labels_map[sport_label_sel]

props_by_sport = [p for p in all_props if not sport_sel or p.get("_sport") == sport_sel]

teams_map = {}
for p in props_by_sport:
    abbrev  = p.get("_team", "")
    display = p.get("_team_display", abbrev)
    if abbrev and display:
        teams_map[abbrev] = display

team_sel_display = st.sidebar.selectbox("Team", ["All"] + sorted(teams_map.values()))
team_abbrev      = None
if team_sel_display != "All":
    team_abbrev = next((k for k, v in teams_map.items() if v == team_sel_display), None)

props_by_team = [p for p in props_by_sport if not team_abbrev or p.get("_team") == team_abbrev]

players_in_team = sorted({
    p.get("_player", "") for p in props_by_team
    if p.get("_player") and len(p.get("_player", "")) > 3
})
player_sel = st.sidebar.selectbox("Player", ["All"] + players_in_team)

# Prop type filter (populates from sport + team selection)
stat_types_available = sorted({
    p.get("attributes", {}).get("stat_type", "")
    for p in props_by_team
    if p.get("attributes", {}).get("stat_type")
})
stat_sel = st.sidebar.multiselect("Prop Type", stat_types_available)

time_label  = st.sidebar.selectbox("Time window", ["Next 6 hours", "Next 12 hours", "Next 24 hours", "All upcoming"])
time_hours  = {"Next 6 hours": 6, "Next 12 hours": 12, "Next 24 hours": 24, "All upcoming": 0}[time_label]

min_trending = st.sidebar.slider("Min PP picks", 0, 500, 0, step=25)

# Apply all filters
filtered_props = props_by_team
if player_sel != "All":
    filtered_props = [p for p in filtered_props if p.get("_player") == player_sel]
if time_hours:
    filtered_props = apply_time_filter(filtered_props, time_hours)
filtered_props = [
    p for p in filtered_props
    if (p.get("attributes", {}).get("trending_count") or 0) >= min_trending
]
if stat_sel:
    filtered_props = [
        p for p in filtered_props
        if p.get("attributes", {}).get("stat_type") in stat_sel
    ]

# Kalshi crossover
def kalshi_for_context(team_display, sport, kalshi_all):
    """
    For the Props tab crossover panel: prefer game markets, fall back to futures.
    Filters by team city name when a team is selected, otherwise by sport.
    """
    game_mkts = [m for m in kalshi_all if m.get("_market_type") == "game"]
    if team_display and team_display != "All":
        city = team_display.split()[0].lower()
        matched = [m for m in game_mkts if city in m.get("title", "").lower()
                   or city in m.get("yes_sub_title", "").lower()]
        if matched:
            return matched
    if sport:
        sport_series = {"NBA": "KXNBAGAME", "NHL": "KXNHLGAME", "MLB": "KXMLBGAME"}
        series = sport_series.get(sport)
        if series:
            return [m for m in game_mkts if m.get("_series") == series]
    return game_mkts

ctx_kalshi = kalshi_for_context(team_sel_display, sport_sel, all_kalshi)


# ── Header ────────────────────────────────────────────────────────────────────

now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
st.markdown("""
<div style="border-bottom:1px solid rgba(0,212,255,0.2);padding-bottom:1rem;margin-bottom:1.5rem;">
  <div style="font-size:2.6rem;font-weight:900;letter-spacing:-0.02em;
              background:linear-gradient(90deg,#fff 0%,#00D4FF 100%);
              -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
    LIVING NEWSPAPER
  </div>
  <div style="color:#00D4FF;font-size:0.75rem;letter-spacing:0.2em;text-transform:uppercase;margin-top:2px;">
    Precision Intelligence &nbsp;·&nbsp; Sports Betting &nbsp;·&nbsp; Real-Time
  </div>
</div>
""", unsafe_allow_html=True)

alerts = data.get("alerts", [])
if alerts:
    st.error("GAME EFFECTIVELY OVER — Free Money MLs")
    for a in alerts:
        st.markdown(
            f"**{a['matchup']}** — {a['score']} ({a['time_left']}s left) | "
            f"Locked: **{a['locked_side'].upper()} ML** | Comeback: {a['comeback_prob']}% | "
            f"**{a['free_money_ml']}**"
        )

tab_props, tab_kalshi, tab_grok = st.tabs(["Props", "Kalshi Markets", "Grok Analysis"])


# ── PROPS TAB ────────────────────────────────────────────────────────────────

with tab_props:
    crumb = " > ".join(filter(None, [
        SPORT_LABELS.get(sport_sel, sport_sel) if sport_sel else None,
        team_sel_display if team_sel_display != "All" else None,
        player_sel if player_sel != "All" else None,
    ])) or "All Sports"
    st.caption(f"Snapshot: {data['_db_ts']}  |  {now_utc}  |  {crumb}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Props", len(filtered_props))
    c2.metric("Kalshi context", len(ctx_kalshi))
    live_n = sum(1 for p in filtered_props if p.get("attributes", {}).get("is_live"))
    c3.metric("Live", live_n)

    # ── Enrichment controls ──
    cache_key = f"{sport_sel}|{team_abbrev}|{player_sel}|{time_hours}|{min_trending}"
    enrichment = st.session_state["enrichment_cache"].get(cache_key)

    enrich_btn_label = (
        f"Get Grok Insight — {len(filtered_props)} props"
        if not enrichment else "Refresh Insight"
    )

    if filtered_props:
        if enrichment and not enrichment.get("_error"):
            st.caption(
                "Sorted by |edge|.  "
                "**Edge** = Grok season avg − PrizePicks line (+ = lean OVER, − = lean UNDER).  "
                "**PP picks** = PrizePicks parlay count (sentiment only, not edge)."
            )
        else:
            st.caption("Click below to load Grok season-avg stats and EV edge for each prop.")

        st.markdown('<div class="enrich-btn">', unsafe_allow_html=True)
        do_enrich = st.button(enrich_btn_label, use_container_width=True, key="enrich_btn")
        st.markdown('</div>', unsafe_allow_html=True)

        if do_enrich:
            with st.spinner(f"Asking Grok for stats on {len(filtered_props)} props..."):
                result = enrich_with_grok(filtered_props)
            st.session_state["enrichment_cache"][cache_key] = result
            enrichment = result
            if result.get("_error"):
                st.error(f"Enrichment error: {result['_error']}")

    df = build_props_df(filtered_props, enrichment=enrichment if enrichment and not enrichment.get("_error") else None)
    if not df.empty:
        st.dataframe(df, width="stretch")
    else:
        st.info("No props match your filters. Try widening the time window or removing filters.")

    # Kalshi crossover — game lines for selected team/sport
    if ctx_kalshi:
        st.markdown("---")
        label = (
            f"Kalshi Game Lines — {team_sel_display}"
            if team_sel_display != "All"
            else f"Kalshi Game Lines — {SPORT_LABELS.get(sport_sel, sport_sel) if sport_sel else 'All sports'}"
        )
        st.subheader(label)
        df_cx = kalshi_games_df(ctx_kalshi)
        if not df_cx.empty:
            st.dataframe(df_cx, width="stretch")
        else:
            st.info("No game lines found for this filter.")


# ── KALSHI MARKETS TAB ────────────────────────────────────────────────────────

with tab_kalshi:
    st.caption(f"Snapshot: {data['_db_ts']}  |  {now_utc}")

    game_markets    = [m for m in all_kalshi if m.get("_market_type") == "game"]
    futures_markets = [m for m in all_kalshi if m.get("_market_type") == "futures"]

    # ── Game Lines (48h window) ──
    st.subheader(f"Game Lines — Next 48 Hours ({len(game_markets) // 2} games)")
    df_games = kalshi_games_df(game_markets)
    if not df_games.empty:
        sport_filter = st.selectbox("Sport", ["All", "NBA", "NHL", "MLB"], key="kalshi_sport")
        search_k     = st.text_input("Search team / game", key="kalshi_search")
        df_show = df_games.copy()
        if sport_filter != "All":
            df_show = df_show[df_show["sport"] == sport_filter]
        if search_k:
            mask = df_show.apply(
                lambda r: search_k.lower() in r["game"].lower()
                       or search_k.lower() in r["fav"].lower()
                       or search_k.lower() in r["dog"].lower(), axis=1
            )
            df_show = df_show[mask]
        st.dataframe(df_show, width="stretch")
        st.caption(
            "fav % / dog % = Kalshi implied win probability.  "
            "vig = market take (lower = tighter market).  "
            "vol = 24h contracts traded."
        )
    else:
        st.info("No game markets in window. Check orchestrator logs.")

    st.markdown("---")

    # ── Championship Futures ──
    st.subheader(f"Championship Futures ({len(futures_markets)} markets)")
    df_fut = kalshi_futures_df(futures_markets)
    if not df_fut.empty:
        st.dataframe(df_fut, width="stretch")
    else:
        st.info("No futures data.")


# ── GROK ANALYSIS TAB ─────────────────────────────────────────────────────────

with tab_grok:
    focus_label = " > ".join(filter(None, [
        SPORT_LABELS.get(sport_sel, sport_sel) if sport_sel else "All Sports",
        team_sel_display if team_sel_display != "All" else None,
        player_sel if player_sel != "All" else None,
    ]))
    st.info(f"Analyzing: **{focus_label}** — {len(filtered_props)} props + {len(ctx_kalshi)} Kalshi markets")

    if st.button("Run Full Analysis"):
        with st.spinner("Calling Grok (~15s)..."):
            result = grok_full_analysis(filtered_props, ctx_kalshi, focus_label)

        if "error" in result:
            st.error(result["error"])
        else:
            if result.get("alert_flag"):
                st.error("ALERT: Blowout detected")
            st.subheader(result.get("analysis_title", "Analysis"))
            c1, c2, c3 = st.columns(3)
            c1.metric("True Prob",  f"{result.get('true_prob','?')}%")
            c2.metric("Fair Line",  result.get("fair_line", "?"))
            c3.metric("Edge",       result.get("edge_at_best_price", "?"))
            st.markdown(f"**EV Threshold:** {result.get('ev_threshold','')}")
            st.markdown(f"**Hit Rate:** {result.get('historical_hit_rate','')}")
            st.markdown(f"**Live Context:** {result.get('live_context','')}")

            ipt = result.get("implied_prob_table")
            if ipt:
                st.subheader("Implied Probability Table")
                st.dataframe(pd.DataFrame(ipt), width="stretch")

            for section, key in [("Breakdown", "detailed_breakdown"), ("Bottom Line", "bottom_line")]:
                items = result.get(key)
                if items:
                    st.subheader(section)
                    for b in items:
                        prefix = "**> " if key == "bottom_line" else "- "
                        suffix = "**" if key == "bottom_line" else ""
                        st.markdown(f"{prefix}{b}{suffix}")
