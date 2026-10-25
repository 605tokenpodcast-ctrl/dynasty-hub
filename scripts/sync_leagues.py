import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

LEAGUE_IDS = [
    "1312263393003991040", # Dante's league
    "1388685966092296192", # Andy's league
    "1312042561786904576", # Hail Mary Jane Congregation
    "1338346687445348352", # Fish's League
    "1389343056888606720", # Roundhouse (Redraft)
    "1329118060811927552"  # All Flex Zone (Redraft)
]

CURRENT_SEASON = "2026"
FUTURE_PICK_SEASONS = ["2027", "2028", "2029"]
REDRAFT_LEAGUE_IDS = ["1389343056888606720", "1329118060811927552"]

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

    for league_id in LEAGUE_IDS:
        print(f"Processing league ID: {league_id}")
        league_info = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}")
        if not league_info:
            continue

        raw_name = league_info.get('name', f"League {league_id}").strip()
        league_key = existing_key_map.get(raw_name.lower(), raw_name)
        existing_rows = master_data.get(league_key, [])
        
        # Bulletproof check: explicit ID match or keyword match for redraft leagues
        is_redraft = (
            league_id in REDRAFT_LEAGUE_IDS or
            any(term in league_key.lower() for term in ["flex", "roundhouse"])
        )

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
        pick_ownership = {}
        if not is_redraft:
            for yr in FUTURE_PICK_SEASONS:
                for rnd in range(1, draft_rounds + 1):
                    for rid in all_roster_ids:
                        pick_ownership[(yr, rnd, rid)] = rid

            for tp in traded_picks:
                yr = str(tp.get('season', ''))
                rnd = tp.get('round')
                orig_rid = tp.get('roster_id')
                curr_rid = tp.get('owner_id')
                if yr in FUTURE_PICK_SEASONS and rnd and orig_rid is not None and curr_rid is not None:
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
            
        live_standings_2026 = []

        for r in rosters:
            rid = r.get('roster_id')
            mgr_label = roster_to_manager.get(rid, f"Team {rid}")
            settings = r.get('settings') or {}
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            fpts = (settings.get('fpts', 0) or 0) + ((settings.get('fpts_decimal', 0) or 0) / 100.0)

            live_standings_2026.append([
                CURRENT_SEASON, mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", "Regular Season", "", ""
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

        # --- 3. FETCH LIVE 2026 WEEKLY BOX SCORES & MATCHUPS (WEEKS 1-18) ---
        new_boxscore_rows = [
            ["--- 2026 WEEKLY PLAYER BOX SCORES & TOP PERFORMERS ---", "", "", "", "", "", ""],
            ["Week", "Team / Manager", "Total Score", "Top Starting Scorer", "Best Bench Scorer", "", ""]
        ]
        new_matchup_rows_2026 = []

        for week in range(1, 19):
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

                if mid is not None:
                    matchup_map.setdefault(mid, []).append({'mgr': mgr, 'pts': pts})

            for mid, pair in sorted(matchup_map.items()):
                if len(pair) == 2:
                    new_matchup_rows_2026.append([
                        CURRENT_SEASON, f"Week {week}", str(mid),
                        pair[0]['mgr'], f"{pair[0]['pts']:.2f}",
                        pair[1]['mgr'], f"{pair[1]['pts']:.2f}"
                    ])

        # --- 4. FETCH LIVE 2026 TRADES ---
        live_trades_2026 = []
        for week in range(1, 19):
            txns = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}") or []
            for tx in txns:
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
                    live_trades_2026.append([
                        CURRENT_SEASON, dt_str, f"Week {week}", teams_involved, breakdown,
                        str(tx.get('transaction_id') or ''), ""
                    ])

        # --- 5. MERGE WITH HISTORICAL SECTIONS SAFELY ---
        if existing_rows:
            historical_standings = []
            historical_trades = []
            historical_matchups = []
            profile_rows = []

            active_sec = None
            for row in existing_rows:
                c0 = str(row[0] if row else '').strip()
                u0 = c0.upper()
                if u0.startswith('---'):
                    if 'PROFILE' in u0: active_sec = 'profile'
                    elif 'STANDINGS' in u0: active_sec = 'standings'
                    elif 'ROSTERS' in u0: active_sec = 'rosters'
                    elif 'TRADE' in u0: active_sec = 'trades'
                    elif 'BOX SCORES' in u0: active_sec = 'boxscores'
                    elif 'MATCHUPS' in u0: active_sec = 'matchups'
                    else: active_sec = 'other'
                    continue

                if not any(str(cell).strip() for cell in row):
                    continue

                if active_sec == 'profile':
                    profile_rows.append(row)
                elif active_sec == 'standings':
                    if c0 not in ('Season', CURRENT_SEASON):
                        historical_standings.append(row)
                elif active_sec == 'trades':
                    if c0 != 'Season':
                        historical_trades.append(row)
                elif active_sec == 'matchups':
                    if c0 not in ('Season', CURRENT_SEASON):
                        historical_matchups.append(row)

            # Dedupe on Sleeper's transaction_id (stored in column 6). Legacy rows written before
            # IDs were stored fall back to (season, date, teams) and get the ID backfilled once.
            merged_trades = [list(r) + [""] * (7 - len(r)) for r in historical_trades]
            known_tx_ids = {str(r[5]).strip() for r in merged_trades if str(r[5]).strip()}
            legacy_by_sig = {
                (str(r[0]).strip(), str(r[1]).strip(), str(r[3]).strip()): r
                for r in merged_trades if not str(r[5]).strip()
            }
            for lt in live_trades_2026:
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
                live_standings_2026 +
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
                new_matchup_rows_2026 +
                historical_matchups
            )
            # Never replace current-season data with less of it: a shrinking row count means
            # some API call silently returned nothing.
            # Trades count only ID-backed rows, so removing legacy duplicates doesn't trip the guard.
            shrunk = [
                sec for sec, ids_only in (('MATCHUPS', False), ('TRADE', True))
                if count_rows(compiled_rows, sec, CURRENT_SEASON, ids_only)
                < count_rows(existing_rows, sec, CURRENT_SEASON, ids_only)
            ]
            if shrunk:
                print(f"ERROR: {league_key}: {CURRENT_SEASON} rows shrank in {shrunk}; keeping existing data.")
                FAILED_URLS.append(f"row-count guard: {league_key} {shrunk}")
            else:
                master_data[league_key] = compiled_rows
        else:
            master_data[league_key] = (
                new_roster_rows +
                new_boxscore_rows +
                [["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""],
                 ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"]] +
                new_matchup_rows_2026
            )

    if FAILED_URLS:
        print(f"ERROR: {len(FAILED_URLS)} request(s) failed; sleeper_leagues_master.json was NOT updated:")
        for url in FAILED_URLS:
            print(f"  - {url}")
        sys.exit(1)

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    print("Successfully merged live Sleeper data while locking out future picks for redraft leagues!")

if __name__ == '__main__':
    build_master_data()
