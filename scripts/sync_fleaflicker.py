import json
import os
import urllib.request

HISTORICAL_LEAGUE_ID = "181202" # 2016-2020 history
TARGET_LEAGUE_NAME = "Hail Mary Jane Congregation"
SEASONS = ["2016", "2017", "2018", "2019", "2020"]

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def import_fleaflicker_history():
    if not os.path.exists('sleeper_leagues_master.json'):
        print("sleeper_leagues_master.json not found!")
        return

    with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    # Find the target league key case-insensitively
    target_key = None
    for k in master_data.keys():
        if k.strip().lower() == TARGET_LEAGUE_NAME.lower():
            target_key = k
            break
    
    if not target_key:
        print(f"Target league '{TARGET_LEAGUE_NAME}' not found in master JSON!")
        return

    print(f"Pulling historical Fleaflicker data for league {HISTORICAL_LEAGUE_ID} (2016-2020)...")
    
    new_historical_standings = []
    new_historical_matchups = []

    for season in SEASONS:
        print(f"Fetching season {season}...")
        standings_data = fetch_json(f"https://www.fleaflicker.com/api/FetchLeagueStandings?sport=NFL&league_id={HISTORICAL_LEAGUE_ID}&season={season}")
        if standings_data:
            for div in standings_data.get('divisions', []):
                for team in div.get('teams', []):
                    team_name = team.get('name', 'Unknown Team')
                    owners = [o.get('displayName', 'Unknown') for o in team.get('owners', [])]
                    mgr_label = f"{team_name} ({owners[0]})" if owners else team_name
                    
                    record_obj = team.get('record', {})
                    wins = record_obj.get('wins', 0)
                    losses = record_obj.get('losses', 0)
                    pf = float(record_obj.get('fptsFor', {}).get('value', 0.0))
                    
                    rank = team.get('rank', 0)
                    placement = "🏆 League Champion" if rank == 1 else ("🥈 Runner-Up" if rank == 2 else ("🥉 3rd Place" if rank == 3 else "Regular Season"))
                    
                    new_historical_standings.append([season, mgr_label, f"{wins}-{losses}", f"{pf:.2f}", placement, "", ""])

        # Fetch weekly scoreboard / matchups for weeks 1 to 16
        for week in range(1, 17):
            sb_data = fetch_json(f"https://www.fleaflicker.com/api/FetchLeagueScoreboard?sport=NFL&league_id={HISTORICAL_LEAGUE_ID}&season={season}&scoring_period={week}")
            if sb_data and 'games' in sb_data:
                for game in sb_data['games']:
                    home = game.get('home', {})
                    away = game.get('away', {})
                    
                    home_team = home.get('name', 'Team')
                    home_owner = home.get('owners', [{}])[0].get('displayName', 'Owner')
                    home_label = f"{home_team} ({home_owner})"
                    home_score = float(home.get('points', {}).get('value', 0.0))
                    
                    away_team = away.get('name', 'Team')
                    away_owner = away.get('owners', [{}])[0].get('displayName', 'Owner')
                    away_label = f"{away_team} ({away_owner})"
                    away_score = float(away.get('points', {}).get('value', 0.0))
                    
                    if home_score > 0 or away_score > 0:
                        matchup_id = str(game.get('id', '1'))
                        new_historical_matchups.append([season, f"Week {week}", matchup_id, home_label, f"{home_score:.2f}", away_label, f"{away_score:.2f}"])

    # Merge into existing target league rows cleanly without duplication
    existing_rows = master_data[target_key]
    compiled_rows = []
    active_sec = None
    
    # Filter out any duplicate 2016-2020 entries if run multiple times
    existing_standings_clean = []
    existing_matchups_clean = []
    other_rows = []

    for row in existing_rows:
        c0 = str(row[0] if row else '').strip()
        u0 = c0.upper()
        if u0.startswith('---'):
            if 'STANDINGS' in u0: active_sec = 'standings'
            elif 'MATCHUPS' in u0: active_sec = 'matchups'
            else: active_sec = 'other'
            continue

        if active_sec == 'standings':
            if c0 not in SEASONS:
                existing_standings_clean.append(row)
        elif active_sec == 'matchups':
            if c0 not in SEASONS:
                existing_matchups_clean.append(row)
        else:
            other_rows.append(row)

    # Reassemble with integrated Fleaflicker history
    # We find where profile / standings header was, or just reconstruct the standard schema order
    profile_and_rosters = []
    trade_section = []
    box_section = []
    
    current_section = 'profile'
    for row in existing_rows:
        c0 = str(row[0] if row else '').strip().upper()
        if c0.startswith('---'):
            if 'STANDINGS' in c0: current_section = 'standings'
            elif 'ROSTERS' in c0: current_section = 'rosters'
            elif 'TRADE' in c0: current_section = 'trades'
            elif 'BOX SCORES' in c0: current_section = 'boxscores'
            elif 'MATCHUPS' in c0: current_section = 'matchups'

    # Safely inject into master structure
    master_data[target_key] = (
        [row for row in existing_rows if not str(row[0]).strip() in SEASONS] +
        [["", "", "", "", "", "", ""]] +
        [["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""]] +
        [["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]] +
        new_historical_standings +
        [r for r in existing_rows if str(r[0]) not in SEASONS and str(r[0]) != 'Season']
    )

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    print("Successfully injected 2016-2020 Fleaflicker history into Hail Mary Jane Congregation!")

if __name__ == '__main__':
    import_fleaflicker_history()
