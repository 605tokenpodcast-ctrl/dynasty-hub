import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

# The leagues come from leagues.json. Each league's season comes from Sleeper itself, so nothing
# here needs editing when a new season starts: a renewed league is found and its new ID saved.
SLEEPER_LEAGUES = league_config.leagues('sleeper')
LEAGUE_IDS = [lg['id'] for lg in SLEEPER_LEAGUES]
REDRAFT_LEAGUE_IDS = [lg['id'] for lg in SLEEPER_LEAGUES if lg.get('type') == 'redraft']
FUTURE_PICK_YEARS = 3  # how many draft classes to list per team
LAST_PLAYOFF_WEEK = 17  # every league's championship is week 17; week 18 is unused
LINEUPS_HEADER = "--- WEEKLY LINEUPS & OPTIMAL SCORES (ALL SEASONS) ---"
MOVES_HEADER = "--- WAIVER & FREE AGENT MOVES (ALL SEASONS) ---"
PLACEMENT_LABELS = {1: "🏆 League Champion", 2: "🥈 Runner-Up", 3: "🥉 3rd Place"}

# URLs that still failed after all retries. Any entry here means the sync is incomplete,
# so the run refuses to overwrite sleeper_leagues_master.json and exits non-zero.
FAILED_URLS = []

def fetch_json(url, retries=4):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            wait = 2 ** (attempt + 1)
            print(f"Fetch failed ({attempt + 1}/{retries}) {url}: {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    FAILED_URLS.append(url)
    return None

def count_rows(rows, section_word, season, with_tx_id=False):
    """Count data rows for `season` inside the section whose header contains `section_word`.
    With with_tx_id, only rows carrying a Sleeper transaction_id (column 6) are counted."""
    count, active = 0, False
    for row in rows or []:
        c0 = str(row[0] if row else '').strip()
        if c0.startswith('---'):
            active = section_word in c0.upper()
            continue
        if active and c0 == season and (not with_tx_id or (len(row) > 5 and str(row[5]).strip())):
            count += 1
    return count

LINEAGE_RE = re.compile(r' -> Resulted in drafting:[^,\]]*')

def trade_content_key(row):
    """Season + breakdown with lineage notes, whitespace and item order normalized."""
    breakdown = re.sub(r'\s+', ' ', LINEAGE_RE.sub('', str(row[4]))).strip()
    sides = []
    for side in breakdown.split(' <---> '):
        m = re.match(r'^(.*? received: )\[(.*)\]$', side)
        sides.append(m.group(1) + ', '.join(sorted(m.group(2).split(', '))) if m else side)
    return (str(row[0]).strip(), ' <---> '.join(sides))

def drop_duplicate_trades(trades):
    """Remove ID-less legacy copies of trades that also exist with a Sleeper transaction_id.

    The old sync re-added the same trade with a shifted date or a renamed team, so its copies
    can't be matched by date. A copy is only dropped when its season and full breakdown match an
    ID-backed row exactly; its "Resulted in drafting" lineage is kept on the surviving row.
    """
    with_id = {trade_content_key(r): r for r in trades if str(r[5]).strip()}
    kept, removed = [], 0
    for r in trades:
        twin = None if str(r[5]).strip() else with_id.get(trade_content_key(r))
        if twin is None:
            kept.append(r)
            continue
        if 'Resulted in drafting:' in str(r[4]) and 'Resulted in drafting:' not in str(twin[4]):
            twin[4] = r[4]
        removed += 1
    return kept, removed

def ordinal(n):
    return f"{n}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"

# Lineup slots each roster position can hold. Fixed slots are filled first, then flex slots
# from the most to the least restrictive, which gives the best possible lineup for these slot types.
SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "DL": {"DL"}, "LB": {"LB"}, "DB": {"DB"},
    "REC_FLEX": {"WR", "TE"}, "WRRB_FLEX": {"WR", "RB"}, "FLEX": {"RB", "WR", "TE"},
    "IDP_FLEX": {"DL", "LB", "DB"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
NON_LINEUP_SLOTS = {"BN", "IR", "TAXI"}

def player_positions(pid, players_data):
    p_info = players_data.get(str(pid), {})
    positions = set(p_info.get('fantasy_positions') or [])
    if p_info.get('position'):
        positions.add(p_info['position'])
    if not positions and not str(pid).isdigit():
        positions.add('DEF')  # team defenses use the team abbreviation as their ID
    return positions

def optimal_score(roster_positions, pool, players_data):
    """Best possible starting score from `pool` ({pid: points}) for the league's roster slots."""
    slots = [s for s in roster_positions if s not in NON_LINEUP_SLOTS]
    slots.sort(key=lambda s: len(SLOT_ELIGIBILITY.get(s, {s})))
    remaining = sorted(pool.items(), key=lambda kv: -kv[1])
    total = 0.0
    for slot in slots:
        allowed = SLOT_ELIGIBILITY.get(slot, {slot})
        for i, (pid, pts) in enumerate(remaining):
            if player_positions(pid, players_data) & allowed:
                total += pts
                remaining.pop(i)
                break
    return total

def build_player_meta(players_data):
    """Age, position, NFL team and years in the league for every active skill player, plus a
    Sleeper ID -> name map (the bot worker uses it to name players in trade alerts)."""
    meta, ids = {}, {}
    for pid, p in players_data.items():
        pos = p.get('position')
        name = p.get('full_name')
        if not name or pos not in ('QB', 'RB', 'WR', 'TE', 'K') or not p.get('active'):
            continue
        age = p.get('age')
        meta[name] = [age if isinstance(age, (int, float)) else None, pos, p.get('team') or 'FA', p.get('years_exp')]
        ids[pid] = f"{name} ({pos})"
    return meta, ids

def lineup_row(season, week, mgr, m, roster_positions, players_data):
    """Full lineup in slot order, plus the best lineup the roster could have started.
    Starters and bench are "Name (Pos) Pts" entries joined by "; "."""
    players_pts = m.get('players_points') or {}
    if not players_pts:
        return None
    pts = float(m.get('points') or 0.0)
    def entry(pid):
        p_name, p_pos, _ = get_player_label(pid, players_data)
        return f"{p_name} ({p_pos}) {float(players_pts.get(pid) or 0.0):.2f}"
    starter_ids = [pid for pid in (m.get('starters') or []) if pid and pid != '0']
    bench_ids = sorted((pid for pid in players_pts if pid not in starter_ids),
                       key=lambda pid: -float(players_pts.get(pid) or 0.0))
    pool = {pid: float(v or 0.0) for pid, v in players_pts.items()}
    best = max(optimal_score(roster_positions, pool, players_data), pts)
    return [str(season), f"Week {week}", mgr, f"{pts:.2f}", f"{best:.2f}",
            "; ".join(entry(pid) for pid in starter_ids),
            "; ".join(entry(pid) for pid in bench_ids)]

def move_row(season, week, tx, roster_to_manager, players_data):
    """A completed waiver claim or free-agent pickup, or None for anything else."""
    if tx.get('type') not in ('waiver', 'free_agent') or tx.get('status') != 'complete':
        return None
    created_ms = tx.get('created', 0)
    dt = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc) if created_ms else None
    rid = (tx.get('roster_ids') or [None])[0]
    def names(d):
        return ", ".join("{} ({})".format(*get_player_label(pid, players_data)[:2]) for pid in (d or {}))
    bid = (tx.get('settings') or {}).get('waiver_bid')
    return [str(season), f"Week {week}", f"{dt.month}/{dt.day}/{dt.year}" if dt else "",
            roster_to_manager.get(rid, f"Team {rid}"),
            "Waiver" if tx.get('type') == 'waiver' else "Free Agent",
            names(tx.get('adds')), names(tx.get('drops')),
            str(bid) if bid is not None else ""]

def manager_labels(league_id):
    """roster_id -> "Team Name (display)" for one Sleeper league."""
    rosters = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/rosters") or []
    users = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/users") or []
    user_map = {}
    for u in users:
        display = u.get('display_name', 'Unknown').strip()
        team_name = ((u.get('metadata') or {}).get('team_name') or '').strip()
        user_map[u.get('user_id')] = f"{team_name} ({display})" if team_name and team_name.lower() != display.lower() else display
    return {r.get('roster_id'): user_map.get(r.get('owner_id'), f"Team {r.get('roster_id')}") for r in rosters}

def backfill_past_seasons(league_info, have_seasons, players_data):
    """Lineups and waiver moves for earlier Sleeper seasons of this league (via previous_league_id).
    Runs once per season: seasons already in the master file are skipped. Old seasons are a
    nice-to-have, so their failed requests are logged but don't block the sync."""
    failed_before = len(FAILED_URLS)
    lineups, moves = [], []
    prev_id = league_info.get('previous_league_id')
    while prev_id and prev_id != '0':
        prev = fetch_json(f"https://api.sleeper.app/v1/league/{prev_id}")
        if not prev:
            break
        season = str(prev.get('season', ''))
        if season and season not in have_seasons:
            print(f"  backfilling {season} lineups and moves from league {prev_id}")
            labels = manager_labels(prev_id)
            positions = prev.get('roster_positions') or []
            for week in range(1, LAST_PLAYOFF_WEEK + 1):
                for m in fetch_json(f"https://api.sleeper.app/v1/league/{prev_id}/matchups/{week}") or []:
                    row = lineup_row(season, week, labels.get(m.get('roster_id'), f"Team {m.get('roster_id')}"), m, positions, players_data)
                    if row and float(row[3]) > 0:
                        lineups.append(row)
            for week in range(1, 19):
                for tx in fetch_json(f"https://api.sleeper.app/v1/league/{prev_id}/transactions/{week}") or []:
                    row = move_row(season, week, tx, labels, players_data)
                    if row:
                        moves.append(row)
        prev_id = prev.get('previous_league_id')
    if len(FAILED_URLS) > failed_before:
        print(f"  WARNING: {len(FAILED_URLS) - failed_before} backfill request(s) failed; dropping this backfill and retrying next run")
        del FAILED_URLS[failed_before:]
        return [], []
    return lineups, moves

def optional_fetches(fn):
    """Run fn() for data the sync can live without: its failed requests are logged, not fatal."""
    failed_before = len(FAILED_URLS)
    result = fn()
    if len(FAILED_URLS) > failed_before:
        print(f"  WARNING: {len(FAILED_URLS) - failed_before} optional request(s) failed; skipped this run")
        del FAILED_URLS[failed_before:]
        return None
    return result

def find_renewed_league(league_info, nfl_state):
    """Next season's league if this Sleeper league has renewed (its previous_league_id points here), else None.

    Sleeper gives a renewed league a new ID and no forward link, so look through the next season's
    leagues of a few of this league's members."""
    season = int(league_info.get('season') or 0)
    if not season or int((nfl_state or {}).get('league_season') or 0) <= season:
        return None
    league_id = str(league_info.get('league_id'))
    users = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/users") or []
    for u in users[:3]:
        for lg in fetch_json(f"https://api.sleeper.app/v1/user/{u.get('user_id')}/leagues/nfl/{season + 1}") or []:
            if str(lg.get('previous_league_id')) == league_id:
                return lg
    return None

def owner_key(label):
    """Sleeper display name from a "Team Name (display)" label, so a renamed team still matches."""
    m = re.search(r'\(([^()]*)\)\s*$', str(label))
    return (m.group(1) if m else str(label)).strip().lower()

def bracket_placements(league_id, roster_labels):
    """owner_key -> placement label from Sleeper's winners bracket, once the title game is final.
    Bracket games carry p = the place they decide: p 1 is the final, p 3 the 3rd-place game."""
    out = {}
    for g in fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/winners_bracket") or []:
        if g.get('p') == 1 and g.get('w') and g.get('l'):
            out[owner_key(roster_labels.get(g['w'], ''))] = PLACEMENT_LABELS[1]
            out[owner_key(roster_labels.get(g['l'], ''))] = PLACEMENT_LABELS[2]
        elif g.get('p') == 3 and g.get('w'):
            out[owner_key(roster_labels.get(g['w'], ''))] = PLACEMENT_LABELS[3]
    return out if PLACEMENT_LABELS[1] in out.values() else {}

def apply_placements(standings_rows, placements):
    """Write placements onto matching standings rows; returns how many rows changed."""
    changed = 0
    for row in standings_rows:
        place = placements.get(owner_key(row[1]))
        if place:
            row[4] = place
            changed += 1
    return changed

def set_profile(profile_rows, key, value):
    for row in profile_rows:
        if str(row[0]).strip() == key:
            row[1] = value
            return
    profile_rows.append([key, value, "", "", "", "", ""])

def get_player_label(pid, players_data):
    p_info = players_data.get(str(pid), {})
    p_name = p_info.get('full_name') or f"{p_info.get('first_name', '')} {p_info.get('last_name', '')}".strip() or str(pid)
    p_pos = p_info.get('position') or 'FLEX'
    p_team = p_info.get('team') or 'FA'
    return p_name, p_pos, p_team

def build_master_data():
    master_data = {}
    if os.path.exists('sleeper_leagues_master.json'):
        try:
            with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
                master_data = json.load(f)
            print("Loaded existing sleeper_leagues_master.json to preserve history.")
        except Exception as e:
            print(f"Could not parse existing master JSON: {e}")

    existing_key_map = {k.strip().lower(): k for k in master_data.keys()}

    print("Fetching NFL players database from Sleeper...")
    players_data = fetch_json("https://api.sleeper.app/v1/players/nfl") or {}
    if not players_data:
        print("ERROR: Sleeper players DB unavailable; aborting without touching the master file.")
        sys.exit(1)

    nfl_state = optional_fetches(lambda: fetch_json("https://api.sleeper.app/v1/state/nfl"))

    for cfg in SLEEPER_LEAGUES:
        league_id = cfg['id']
        print(f"Processing league ID: {league_id}")
        league_info = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}")
        if not league_info:
            continue

        renewed = optional_fetches(lambda: find_renewed_league(league_info, nfl_state))
        if renewed:
            new_id = str(renewed['league_id'])
            new_info = fetch_json(f"https://api.sleeper.app/v1/league/{new_id}")
            if not new_info:
                continue
            print(f"  league renewed for {new_info.get('season')}: {league_id} -> {new_id} (saved to leagues.json)")
            league_config.set_league_id(league_id, new_id)
            league_id, league_info = new_id, new_info

        season = str(league_info.get('season') or '').strip()
        if not season:
            print(f"ERROR: league {league_id} has no season; skipping")
            FAILED_URLS.append(f"no season: {league_id}")
            continue

        raw_name = league_info.get('name', f"League {league_id}").strip()
        league_key = existing_key_map.get(raw_name.lower(), raw_name)
        existing_rows = master_data.get(league_key, [])
        
        is_redraft = cfg.get('type') == 'redraft'

        draft_rounds = league_info.get('settings', {}).get('draft_rounds', 4)
        rosters = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/rosters") or []
        users = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/users") or []
        traded_picks = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/traded_picks") or []

        user_map = {}
        for u in users:
            uid = u.get('user_id')
            display = u.get('display_name', 'Unknown').strip()
            metadata = u.get('metadata') or {}
            team_name = (metadata.get('team_name') or '').strip()
            if team_name and team_name.lower() != display.lower():
                user_map[uid] = f"{team_name} ({display})"
            else:
                user_map[uid] = display

        roster_to_manager = {}
        all_roster_ids = []
        for r in rosters:
            rid = r.get('roster_id')
            if rid is not None:
                all_roster_ids.append(rid)
            uid = r.get('owner_id')
            roster_to_manager[rid] = user_map.get(uid, f"Team {rid}")

        # --- 1. ACCURATE FUTURE DRAFT PICK ENGINE (Dynasty Only) ---
        # Until this season's rookie draft is done, its picks are still future picks
        first_pick_year = int(season) + (0 if league_info.get('status') in ('pre_draft', 'drafting') else 1)
        future_pick_seasons = [str(y) for y in range(first_pick_year, first_pick_year + FUTURE_PICK_YEARS)]
        pick_ownership = {}
        if not is_redraft:
            for yr in future_pick_seasons:
                for rnd in range(1, draft_rounds + 1):
                    for rid in all_roster_ids:
                        pick_ownership[(yr, rnd, rid)] = rid

            for tp in traded_picks:
                yr = str(tp.get('season', ''))
                rnd = tp.get('round')
                orig_rid = tp.get('roster_id')
                curr_rid = tp.get('owner_id')
                if yr in future_pick_seasons and rnd and orig_rid is not None and curr_rid is not None:
                    pick_ownership[(yr, rnd, orig_rid)] = curr_rid

        # --- 2. BUILD CURRENT ROSTERS & STANDINGS ---
        if is_redraft:
            new_roster_rows = [
                ["--- CURRENT ROSTERS ---", "", "", "", "", "", ""],
                ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "", "", ""]
            ]
        else:
            new_roster_rows = [
                ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
                ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
            ]
            
        live_standings = []

        for r in rosters:
            rid = r.get('roster_id')
            mgr_label = roster_to_manager.get(rid, f"Team {rid}")
            settings = r.get('settings') or {}
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            fpts = (settings.get('fpts', 0) or 0) + ((settings.get('fpts_decimal', 0) or 0) / 100.0)

            live_standings.append([
                season, mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", "Regular Season", "", ""
            ])

            player_strs = []
            for pid in (r.get('players') or []):
                p_name, p_pos, p_team = get_player_label(pid, players_data)
                player_strs.append(f"{p_name} ({p_pos} - {p_team})")

            if is_redraft:
                new_roster_rows.append([
                    mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", ", ".join(player_strs), "", "", ""
                ])
            else:
                owned_picks = []
                for (yr, rnd, orig_rid), owner_rid in sorted(pick_ownership.items()):
                    if owner_rid == rid:
                        owned_picks.append(f"{yr} Mid Round {rnd}")

                picks_str = ", ".join(owned_picks) if owned_picks else "None"
                new_roster_rows.append([
                    mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", ", ".join(player_strs), picks_str, "", ""
                ])

        # Final placements, once the championship game is decided
        placements = optional_fetches(lambda: bracket_placements(league_id, roster_to_manager)) or {}
        apply_placements(live_standings, placements)

        # --- 3. FETCH THIS SEASON'S WEEKLY BOX SCORES & MATCHUPS (WEEKS 1-17) ---
        new_boxscore_rows = [
            [f"--- {season} WEEKLY PLAYER BOX SCORES & TOP PERFORMERS ---", "", "", "", "", "", ""],
            ["Week", "Team / Manager", "Total Score", "Top Starting Scorer", "Best Bench Scorer", "", ""]
        ]
        new_matchup_rows = []
        new_lineup_rows = []
        roster_positions = league_info.get('roster_positions') or []

        for week in range(1, LAST_PLAYOFF_WEEK + 1):
            matchups = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}") or []
            matchup_map = {}
            for m in matchups:
                mid = m.get('matchup_id')
                rid = m.get('roster_id')
                mgr = roster_to_manager.get(rid, f"Team {rid}")
                pts = float(m.get('points') or 0.0)

                starters = m.get('starters') or []
                players_pts = m.get('players_points') or {}

                top_st_str = "None (0.00)"
                top_st_pts = -1.0
                top_bn_str = "None (0.00)"
                top_bn_pts = -1.0

                for pid, pval in players_pts.items():
                    pval_f = float(pval or 0.0)
                    p_name, p_pos, _ = get_player_label(pid, players_data)
                    label = f"{p_name} ({p_pos}) ({pval_f:.2f})"
                    if pid in starters:
                        if pval_f > top_st_pts:
                            top_st_pts = pval_f
                            top_st_str = label
                    else:
                        if pval_f > top_bn_pts:
                            top_bn_pts = pval_f
                            top_bn_str = label

                new_boxscore_rows.append([
                    f"Week {week}", mgr, f"{pts:.2f}", top_st_str, top_bn_str, "", ""
                ])

                row = lineup_row(season, week, mgr, m, roster_positions, players_data)
                if row:
                    new_lineup_rows.append(row)

                if mid is not None:
                    matchup_map.setdefault(mid, []).append({'mgr': mgr, 'pts': pts})

            for mid, pair in sorted(matchup_map.items()):
                if len(pair) == 2:
                    new_matchup_rows.append([
                        season, f"Week {week}", str(mid),
                        pair[0]['mgr'], f"{pair[0]['pts']:.2f}",
                        pair[1]['mgr'], f"{pair[1]['pts']:.2f}"
                    ])

        # --- 4. FETCH THIS SEASON'S TRADES ---
        live_trades = []
        new_move_rows = []
        for week in range(1, 19):
            txns = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}") or []
            for tx in txns:
                row = move_row(season, week, tx, roster_to_manager, players_data)
                if row:
                    new_move_rows.append(row)
                if tx.get('type') == 'trade' and tx.get('status') == 'complete':
                    created_ms = tx.get('created', 0)
                    dt = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc) if created_ms else None
                    dt_str = f"{dt.month}/{dt.day}/{dt.year}" if dt else ""
                    rids = tx.get('roster_ids') or []
                    if len(rids) < 2:
                        continue
                    teams_involved = " & ".join(roster_to_manager.get(rid, f"Team {rid}") for rid in rids)
                    adds = tx.get('adds') or {}
                    draft_picks_tx = tx.get('draft_picks') or []

                    side_strs = []
                    for rid in rids:
                        mgr = roster_to_manager.get(rid, f"Team {rid}")
                        received_items = []
                        for pid, target_rid in adds.items():
                            if target_rid == rid:
                                p_name, p_pos, _ = get_player_label(pid, players_data)
                                received_items.append(f"{p_name} ({p_pos})")
                        for dp in draft_picks_tx:
                            if dp.get('owner_id') == rid:
                                orig_mgr = roster_to_manager.get(dp.get('roster_id'), f"Team {dp.get('roster_id')}")
                                received_items.append(f"{dp.get('season')} Round {ordinal(dp.get('round', 1))} Pick (originally from {orig_mgr})")
                        items_joined = ", ".join(received_items) if received_items else "Nothing"
                        side_strs.append(f"{mgr} received: [{items_joined}]")

                    breakdown = " <---> ".join(side_strs)
                    live_trades.append([
                        season, dt_str, f"Week {week}", teams_involved, breakdown,
                        str(tx.get('transaction_id') or ''), ""
                    ])

        # --- 5. MERGE WITH HISTORICAL SECTIONS SAFELY ---
        # A league that isn't in the master file yet starts with empty history and a generated
        # profile, so it gets the same sections (and League ID) as every other league.
        historical_standings = []
        historical_trades = []
        historical_matchups = []
        historical_lineups = []
        historical_moves = []
        profile_rows = []

        if existing_rows:
            active_sec = None
            for row in existing_rows:
                c0 = str(row[0] if row else '').strip()
                u0 = c0.upper()
                if u0.startswith('---'):
                    if 'PROFILE' in u0: active_sec = 'profile'
                    elif 'STANDINGS' in u0: active_sec = 'standings'
                    elif 'ROSTERS' in u0: active_sec = 'rosters'
                    elif 'TRADE' in u0: active_sec = 'trades'
                    elif 'LINEUPS' in u0: active_sec = 'lineups'
                    elif 'FREE AGENT' in u0: active_sec = 'moves'
                    elif 'BOX SCORES' in u0: active_sec = 'boxscores'
                    elif 'MATCHUPS' in u0: active_sec = 'matchups'
                    else: active_sec = 'other'
                    continue

                if not any(str(cell).strip() for cell in row):
                    continue

                if active_sec == 'profile':
                    profile_rows.append(row)
                elif active_sec == 'standings':
                    if c0 not in ('Season', season):
                        historical_standings.append(row)
                elif active_sec == 'trades':
                    if c0 != 'Season':
                        historical_trades.append(row)
                elif active_sec == 'matchups':
                    if c0 not in ('Season', season):
                        historical_matchups.append(row)
                elif active_sec == 'lineups':
                    if c0 not in ('Season', season):
                        historical_lineups.append(row)
                elif active_sec == 'moves':
                    if c0 not in ('Season', season):
                        historical_moves.append(row)

        have_seasons = {str(r[0]).strip() for r in historical_lineups}
        past_lineups, past_moves = backfill_past_seasons(league_info, have_seasons, players_data)
        historical_lineups = past_lineups + historical_lineups
        historical_moves = past_moves + historical_moves

        if not profile_rows:
            profile_rows = [
                ["League Name", raw_name, "", "", "", "", ""],
                ["League Type", "Redraft" if is_redraft else "Dynasty", "", "", "", "", ""],
            ]
        # Kept current on every run: the site reads the League ID for live scores and the playoff
        # settings for this season's playoff week and cutoff.
        league_settings = league_info.get('settings') or {}
        set_profile(profile_rows, "League ID", league_id)
        set_profile(profile_rows, "Current Season", season)
        if league_settings.get('playoff_week_start'):
            set_profile(profile_rows, "Playoff Start Week", str(league_settings['playoff_week_start']))
        if league_settings.get('playoff_teams'):
            set_profile(profile_rows, "Playoff Teams", str(league_settings['playoff_teams']))

        # Last season's placements, if the sync never saw its title game (e.g. it renewed first)
        prev_season = str(int(season) - 1)
        prev_rows = [r for r in historical_standings if str(r[0]).strip() == prev_season]
        prev_id = str(league_info.get('previous_league_id') or '')
        if prev_rows and prev_id not in ('', '0', 'None') and not any('Champion' in str(r[4]) for r in prev_rows):
            prev_places = optional_fetches(lambda: bracket_placements(prev_id, manager_labels(prev_id))) or {}
            if apply_placements(prev_rows, prev_places):
                print(f"  recorded {prev_season} placements from league {prev_id}")

        # Dedupe on Sleeper's transaction_id (stored in column 6). Legacy rows written before
        # IDs were stored fall back to (season, date, teams) and get the ID backfilled once.
        merged_trades = [list(r) + [""] * (7 - len(r)) for r in historical_trades]
        known_tx_ids = {str(r[5]).strip() for r in merged_trades if str(r[5]).strip()}
        legacy_by_sig = {
            (str(r[0]).strip(), str(r[1]).strip(), str(r[3]).strip()): r
            for r in merged_trades if not str(r[5]).strip()
        }
        for lt in live_trades:
            tx_id = lt[5]
            if tx_id and tx_id in known_tx_ids:
                continue
            legacy = legacy_by_sig.pop((lt[0], lt[1], lt[3]), None)
            if legacy is not None:
                legacy[5] = tx_id
            else:
                merged_trades.insert(0, lt)
            if tx_id:
                known_tx_ids.add(tx_id)
        merged_trades, dupes = drop_duplicate_trades(merged_trades)
        if dupes:
            print(f"{league_key}: removed {dupes} duplicate legacy trade row(s)")

        compiled_rows = (
            [["--- LEAGUE PROFILE ---", "", "", "", "", "", ""]] +
            profile_rows +
            [["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""],
             ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]] +
            live_standings +
            historical_standings +
            [["", "", "", "", "", "", ""]] +
            new_roster_rows +
            [["", "", "", "", "", "", ""],
             ["--- TRADE HISTORY (ALL-TIME & ALL SEASONS) ---", "", "", "", "", "", ""],
             ["Season", "Date", "Week", "Teams Involved", "Trade Breakdown", "", ""]] +
            merged_trades +
            [["", "", "", "", "", "", ""]] +
            new_boxscore_rows +
            [["", "", "", "", "", "", ""],
             ["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""],
             ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"]] +
            new_matchup_rows +
            historical_matchups +
            [["", "", "", "", "", "", ""],
             [LINEUPS_HEADER, "", "", "", "", "", ""],
             ["Season", "Week", "Team / Manager", "Score", "Optimal Score", "Starters (Name (Pos) Pts)", "Bench (Name (Pos) Pts)"]] +
            new_lineup_rows +
            historical_lineups +
            [["", "", "", "", "", "", ""],
             [MOVES_HEADER, "", "", "", "", "", "", ""],
             ["Season", "Week", "Date", "Team / Manager", "Type", "Added", "Dropped", "FAAB Bid"]] +
            new_move_rows +
            historical_moves
        )
        # Never replace current-season data with less of it: a shrinking row count means
        # some API call silently returned nothing.
        # Trades count only ID-backed rows, so removing legacy duplicates doesn't trip the guard.
        shrunk = [
            sec for sec, ids_only in (('MATCHUPS', False), ('TRADE', True), ('LINEUPS', False), ('FREE AGENT', False))
            if count_rows(compiled_rows, sec, season, ids_only)
            < count_rows(existing_rows, sec, season, ids_only)
        ]
        if shrunk:
            print(f"ERROR: {league_key}: {season} rows shrank in {shrunk}; keeping existing data.")
            FAILED_URLS.append(f"row-count guard: {league_key} {shrunk}")
        else:
            master_data[league_key] = compiled_rows

    if FAILED_URLS:
        print(f"ERROR: {len(FAILED_URLS)} request(s) failed; sleeper_leagues_master.json was NOT updated:")
        for url in FAILED_URLS:
            print(f"  - {url}")
        sys.exit(1)

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    meta, ids = build_player_meta(players_data)
    with open('player_meta.json', 'w', encoding='utf-8') as f:
        json.dump({"generated_at": int(time.time()), "fields": ["age", "pos", "team", "years_exp"],
                   "players": meta, "ids": ids}, f, separators=(',', ':'))

    print("Successfully merged live Sleeper data while locking out future picks for redraft leagues!")

if __name__ == '__main__':
    build_master_data()
