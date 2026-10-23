import json
import urllib.request

# Your 6 active Sleeper League IDs
LEAGUE_IDS = [
    "1312263393003991040", # Dante's league
    "1388685966092296192", # Andy's league
    "1312042561786904576", # Hail Mary Jane Congregation
    "1338346687445348352", # Fish's League
    "1389343056888606720", # Roundhouse
    "1329118060811927552"  # All Flex Zone
]

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def build_master_data():
    master_data = {}
    
    print("Fetching NFL players database from Sleeper...")
    players_data = fetch_json("https://api.sleeper.app/v1/players/nfl") or {}

    for league_id in LEAGUE_IDS:
        print(f"Processing league ID: {league_id}")
        league_info = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}")
        if not league_info:
            continue
        
        league_name = league_info.get('name', f"League {league_id}").strip()
        rosters = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/rosters") or []
        users = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/users") or []
        traded_picks = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/traded_picks") or []
        
        user_map = {}
        for u in users:
            uid = u.get('user_id')
            display = u.get('display_name', 'Unknown')
            metadata = u.get('metadata', {})
            team_name = metadata.get('team_name') or display
            user_map[uid] = f"{team_name} ({display})"

        # Map roster_id to manager label
        roster_to_manager = {}
        for r in rosters:
            rid = r.get('roster_id')
            uid = r.get('owner_id')
            roster_to_manager[rid] = user_map.get(uid, f"Team {rid}")

        # Build structured sheet rows matching your master format
        rows = [
            ["--- LEAGUE PROFILE ---", "", "", "", "", "", ""],
            ["League Name", league_name, "", "", "", "", ""],
            ["League ID", league_id, "", "", "", "", ""],
            ["Current Season", league_info.get('season', '2026'), "", "", "", "", ""],
            ["Roster Positions", ", ".join(league_info.get('roster_positions', [])), "", "", "", "", ""],
            ["Scoring Settings", "", "", "", "", "", json.dumps(league_info.get('scoring_settings', {}))],
            ["", "", "", "", "", "", ""],
            ["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""],
            ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]
        ]

        # Populate current 2026 standings placeholder from live rosters
        for r in rosters:
            rid = r.get('roster_id')
            mgr_label = roster_to_manager.get(rid, f"Team {rid}")
            settings = r.get('settings', {})
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            ties = settings.get('ties', 0)
            fpts = (settings.get('fpts', 0) or 0) + (settings.get('fpts_decimal', 0) / 100 if settings.get('fpts_decimal') else 0)
            rows.append(["2026", mgr_label, f"{wins}-{losses}" + (f"-{ties}" if ties > 0 else ""), f"{fpts:.2f}", "Regular Season", "", ""])

        rows.append(["", "", "", "", "", "", ""])
        rows.append(["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""])
        rows.append(["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""])

        for r in rosters:
            rid = r.get('roster_id')
            mgr_label = roster_to_manager.get(rid, f"Team {rid}")
            settings = r.get('settings', {})
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            fpts = (settings.get('fpts', 0) or 0) + (settings.get('fpts_decimal', 0) / 100 if settings.get('fpts_decimal') else 0)
            
            # Process Roster Players
            player_strs = []
            for pid in r.get('players', []):
                p_info = players_data.get(pid, {})
                p_name = p_info.get('full_name', pid)
                p_pos = p_info.get('position', 'FLEX')
                p_team = p_info.get('team', 'FA')
                player_strs.append(f"{p_name} ({p_pos} - {p_team})")

            # Process Future Draft Picks held by this roster
            owned_picks = []
            for tp in traded_picks:
                if tp.get('owner_id') == r.get('owner_id'):
                    season_yr = tp.get('season')
                    round_num = tp.get('round')
                    owned_picks.append(f"{season_yr} Mid Round {round_num}")

            picks_str = ", ".join(owned_picks) if owned_picks else "None"
            rows.append([mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", ", ".join(player_strs), picks_str, "", ""])

        rows.append(["", "", "", "", "", "", ""])
        rows.append(["--- TRADE HISTORY (ALL-TIME & ALL SEASONS) ---", "", "", "", "", "", ""])
        rows.append(["Season", "Date", "Week", "Teams Involved", "Trade Breakdown", "", ""])

        # Fetch transactions for recent weeks to populate live trades
        for week in range(1, 15):
            txs = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}") or []
            for tx in txs:
                if tx.get('type') == 'trade':
                    status_tl = tx.get('status')
                    if status_tl == 'complete':
                        adds = tx.get('adds') or {}
                        roster_ids = tx.get('roster_ids', [])
                        involved = [roster_to_manager.get(rid, f"Team {rid}") for rid in roster_ids]
                        teams_str = " & ".join(involved)
                        rows.append(["2026", "Live Sync", f"Week {week}", teams_str, f"Completed trade involving {len(adds)} assets.", "", ""])

        rows.append(["", "", "", "", "", "", ""])
        rows.append(["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""])
        rows.append(["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"])

        # Fetch live 2026 matchups
        for week in range(1, 15):
            matchups = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}") or []
            matchup_map = {}
            for m in matchups:
                mid = m.get('matchup_id')
                if mid is not None:
                    if mid not in matchup_map: matchup_map[mid] = []
                    matchup_map[mid].append(m)

            for mid, pair in matchup_map.items():
                if len(pair) == 2:
                    t1_mgr = roster_to_manager.get(pair[0].get('roster_id'), "Team 1")
                    t1_pts = pair[0].get('points', 0)
                    t2_mgr = roster_to_manager.get(pair[1].get('roster_id'), "Team 2")
                    t2_pts = pair[1].get('points', 0)
                    rows.append(["2026", f"Week {week}", str(mid), t1_mgr, f"{t1_pts:.2f}", t2_mgr, f"{t2_pts:.2f}"])

        master_data[league_name] = rows

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, indent=2)
    
    print("Successfully generated sleeper_leagues_master.json for all 6 leagues!")

if __name__ == '__main__':
    build_master_data()
