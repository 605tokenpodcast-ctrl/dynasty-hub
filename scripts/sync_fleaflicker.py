import json
import os
import urllib.request

HISTORICAL_LEAGUE_ID = "181202"  # 2016-2020 history to merge into Hail Mary Jane
TARGET_LEAGUE_NAME = "Hail Mary Jane Congregation"
HISTORICAL_SEASONS = ["2016", "2017", "2018", "2019", "2020"]

ACTIVE_FLEA_ID = "165455"        # Current active league (2015-Present)
ACTIVE_FLEA_NAME = "Fleaflicker Main League"
ACTIVE_SEASONS = ["2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def parse_fleaflicker_standings(season, league_id):
    standings_rows = []
    data = fetch_json(f"https://www.fleaflicker.com/api/FetchLeagueStandings?sport=NFL&league_id={league_id}&season={season}")
    if not data:
        return standings_rows

    for div in data.get('divisions', []):
        for team in div.get('teams', []):
            team_name = team.get('name', 'Team')
            owners = team.get('owners', [])
            owner_name = owners[0].get('displayName', 'Owner') if owners else 'Owner'
            mgr_label = f"{team_name} ({owner_name})"
            
            record = team.get('record', {})
            wins = record.get('wins', 0)
            losses = record.get('losses', 0)
            
            # Fleaflicker points for value formatting
            pf_obj = record.get('pointsFor') or record.get('fptsFor') or {}
            pf = float(pf_obj.get('value', 0.0))
            
            rank = team.get('rank', 0)
            placement = "🏆 League Champion" if rank == 1 else ("🥈 Runner-Up" if rank == 2 else ("🥉 3rd Place" if rank == 3 else "Regular Season"))
            standings_rows.append([season, mgr_label, f"{wins}-{losses}", f"{pf:.2f}", placement, "", ""])
            
    return standings_rows

def parse_fleaflicker_matchups(season, league_id):
    matchup_rows = []
    for week in range(1, 18):
        sb_data = fetch_json(f"https://www.fleaflicker.com/api/FetchLeagueScoreboard?sport=NFL&league_id={league_id}&season={season}&scoring_period={week}")
        if sb_data and 'games' in sb_data:
            for game in sb_data['games']:
                h = game.get('home', {})
                a = game.get('away', {})
                
                h_team = h.get('name', 'Team')
                h_owner = h.get('owners', [{}])[0].get('displayName', 'Owner') if h.get('owners') else 'Owner'
                h_label = f"{h_team} ({h_owner})"
                h_score = float(h.get('points', {}).get('value', 0.0))
                
                a_team = a.get('name', 'Team')
                a_owner = a.get('owners', [{}])[0].get('displayName', 'Owner') if a.get('owners') else 'Owner'
                a_label = f"{a_team} ({a_owner})"
                a_score = float(a.get('points', {}).get('value', 0.0))
                
                if h_score > 0 or a_score > 0:
                    mid = str(game.get('id', '1'))
                    matchup_rows.append([season, f"Week {week}", mid, h_label, f"{h_score:.2f}", a_label, f"{a_score:.2f}"])
    return matchup_rows

def build_fleaflicker_data():
    if not os.path.exists('sleeper_leagues_master.json'):
        print("sleeper_leagues_master.json not found!")
        return

    with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    # --- PART 1: Merge 2016-2020 cleanly into Hail Mary Jane Congregation ---
    target_key = None
    for k in master_data.keys():
        if k.strip().lower() == TARGET_LEAGUE_NAME.lower():
            target_key = k
            break

    if target_key:
        print(f"Syncing 2016-2020 history from {HISTORICAL_LEAGUE_ID} into {target_key}...")
        existing_rows = master_data[target_key]
        
        # Strip out old historical seasons entirely so we don't duplicate/double-count
        clean_rows = []
        skip_mode = False
        for r in existing_rows:
            c0 = str(r[0] if r else '').strip()
            if c0.startswith('---'):
                skip_mode = False
            if c0 in HISTORICAL_SEASONS:
                continue
            clean_rows.append(r)

        new_hist_standings = []
        new_hist_matchups = []
        for season in HISTORICAL_SEASONS:
            new_hist_standings.extend(parse_fleaflicker_standings(season, HISTORICAL_LEAGUE_ID))
            new_hist_matchups.extend(parse_fleaflicker_matchups(season, HISTORICAL_LEAGUE_ID))

        # Rebuild clean structure for target league
        profile_part = []
        standings_header = ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]
        matchups_header = ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"]
        
        # Extract existing non-historical rows (like 2021-2026 Sleeper data)
        other_standings = [r for r in clean_rows if len(r) > 4 and "Regular Season" in str(r[4]) or "Champion" in str(r[4]) or "Place" in str(r[4]) or "Runner-Up" in str(r[4])]
        other_matchups = [r for r in clean_rows if len(r) == 7 and str(r[1]).startswith("Week")]

        master_data[target_key] = (
            [r for r in clean_rows if not str(r[0]).upper().startswith('---')] +
            [["", "", "", "", "", "", ""]] +
            [["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""]] +
            [standings_header] +
            new_hist_standings + 
            [r for r in other_standings if str(r[0]) not in HISTORICAL_SEASONS] +
            [["", "", "", "", "", "", ""]] +
            [["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""]] +
            [matchups_header] +
            new_hist_matchups +
            [r for r in other_matchups if str(r[0]) not in HISTORICAL_SEASONS]
        )

    # --- PART 2: Build Active/Historical Dataset for Fleaflicker League 165455 ---
    print(f"Building dataset for active Fleaflicker league {ACTIVE_FLEA_ID}...")
    flea_standings = []
    flea_matchups = []

    for season in ACTIVE_SEASONS:
        flea_standings.extend(parse_fleaflicker_standings(season, ACTIVE_FLEA_ID))
        flea_matchups.extend(parse_fleaflicker_matchups(season, ACTIVE_FLEA_ID))

    flea_rosters = [
        ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
        ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
    ]

    master_data[ACTIVE_FLEA_NAME] = (
        [["--- LEAGUE PROFILE ---", "", "", "", "", "", ""],
         ["League Name", ACTIVE_FLEA_NAME, "", "", "", "", ""],
         ["League ID", ACTIVE_FLEA_ID, "", "", "", "", ""],
         ["Current Season", "2026", "", "", "", "", ""]] +
        [["", "", "", "", "", "", ""]] +
        [["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""],
         ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]] +
        flea_standings +
        [["", "", "", "", "", "", ""]] +
        flea_rosters +
        [["", "", "", "", "", "", ""]] +
        [["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""],
         ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"]] +
        flea_matchups
    )

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    print("Successfully fixed and synchronized Fleaflicker data without duplication!")

if __name__ == '__main__':
    build_fleaflicker_data()
