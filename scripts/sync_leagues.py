import json
import os
import urllib.request

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
    # Load existing master JSON if it exists to preserve historical records, trophies, and past logs
    master_data = {}
    if os.path.exists('sleeper_leagues_master.json'):
        try:
            with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
                master_data = json.load(f)
            print("Loaded existing sleeper_leagues_master.json to preserve history.")
        except Exception as e:
            print(f"Could not parse existing master JSON: {e}")

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

        roster_to_manager = {}
        for r in rosters:
            rid = r.get('roster_id')
            uid = r.get('owner_id')
            roster_to_manager[rid] = user_map.get(uid, f"Team {rid}")

        # If league already exists in master JSON, preserve its header & historical sections (like Trophy Room / past trades)
        existing_rows = master_data.get(league_name, [])
        
        # Build fresh rows for current 2026 Rosters & Matchups
        new_roster_rows = [
            ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
            ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
        ]

        for r in rosters:
            rid = r.get('roster_id')
            mgr_label = roster_to_manager.get(rid, f"Team {rid}")
            settings = r.get('settings', {})
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            fpts = (settings.get('fpts', 0) or 0) + (settings.get('fpts_decimal', 0) / 100 if settings.get('fpts_decimal') else 0)
            
            player_strs = []
            for pid in r.get('players', []):
                p_info = players_data.get(pid, {})
                p_name = p_info.get('full_name', pid)
                p_pos = p_info.get('position', 'FLEX')
                p_team = p_info.get('team', 'FA')
                player_strs.append(f"{p_name} ({p_pos} - {p_team})")

            owned_picks = []
            for tp in traded_picks:
                if tp.get('owner_id') == r.get('owner_id'):
                    season_yr = tp.get('season')
                    round_num = tp.get('round')
                    owned_picks.append(f"{season_yr} Mid Round {round_num}")

            picks_str = ", ".join(owned_picks) if owned_picks else "None"
            new_roster_rows.append([mgr_label, f"{wins}-{losses}", f"{fpts:.2f}", ", ".join(player_strs), picks_str, "", ""])

        # Fetch live 2026 matchups for Weeks 1-14 (Box scores / Bench Blunders)
        new_boxscore_rows = [
            ["--- BOX SCORES & BENCH BLUNDERS ---", "", "", "", "", "", ""],
            ["Week", "Team / Manager", "Total Score", "Top Starter", "Top Bench", "", ""]
        ]
        
        new_matchup_rows = [
            ["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""],
            ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"]
        ]

        for week in range(1, 15):
            matchups = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}") or []
            matchup_map = {}
            for m in matchups:
                mid = m.get('matchup_id')
                rid = m.get('roster_id')
                mgr = roster_to_manager.get(rid, f"Team {rid}")
                pts = m.get('points', 0)
                
                # Parse players points if available in starters/players
                starters = m.get('starters', [])
                players_pts = m.get('players_points', {})
                
                # Find top starter and top bench player for Bench Blunders tab
                top_st_name, top_st_pts = "Starter", 0
                top_bn_name, top_bn_pts = "None", 0
                for pid, pval in players_pts.items():
                    p_info = players_data.get(pid, {})
                    p_name = p_info.get('full_name', pid)
                    if pid in starters:
                        if pval > top_st_pts: top_st_name, top_st_pts = p_name, pval
                    else:
                        if pval > top_bn_pts: top_bn_name, top_bn_pts = p_name, pval

                if mid is not None:
                    if mid not in matchup_map: matchup_map[mid] = []
                    matchup_map[mid].append({'mgr': mgr, 'pts': pts})

                if pts > 0:
                    new_boxscore_rows.append([f"Week {week}", mgr, f"{pts:.2f}", f"{top_st_name} ({top_st_pts})", f"{top_bn_name} ({top_bn_pts})", "", ""])

            for mid, pair in matchup_map.items():
                if len(pair) == 2:
                    new_matchup_rows.append(["2026", f"Week {week}", str(mid), pair[0]['mgr'], f"{pair[0]['pts']:.2f}", pair[1]['mgr'], f"{pair[1]['pts']:.2f}"])

        # If we have existing history for this league, we can selectively update the 2026 sections
        # while keeping past seasons (2023-2025 championships and older trades) intact.
        if existing_rows:
            # Keep profile, past standings, and historical trade logs from existing_rows,
            # but update the live 2026 rosters, box scores, and matchups.
            compiled_rows = []
            skip_section = False
            for row in existing_rows:
                c0 = str(row[0]).strip().upper()
                if c0.startswith('---'):
                    skip_section = any(k in c0 for k in ['ROSTERS', 'BOX SCORES', 'MATCHUPS'])
                if not skip_section:
                    compiled_rows.append(row)
            
            # Append newly fetched 2026 sections
            compiled_rows.extend([["", "", "", "", "", "", ""]])
            compiled_rows.extend(new_roster_rows)
            compiled_rows.extend([["", "", "", "", "", "", ""]])
            compiled_rows.extend(new_boxscore_rows)
            compiled_rows.extend([["", "", "", "", "", "", ""]])
            compiled_rows.extend(new_matchup_rows)
            master_data[league_name] = compiled_rows
        else:
            # Fallback if brand new
            master_data[league_name] = new_roster_rows + new_boxscore_rows + new_matchup_rows

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, indent=2)
    
    print("Successfully merged live Sleeper data while preserving history!")

if __name__ == '__main__':
    build_master_data()
