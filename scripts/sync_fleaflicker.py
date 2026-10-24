import json
import os
import urllib.request

HISTORICAL_LEAGUE_ID = "181202"  # 2016-2020 history for Hail Mary Jane
TARGET_LEAGUE_NAME = "Hail Mary Jane Congregation"
HISTORICAL_SEASONS = ["2016", "2017", "2018", "2019", "2020"]

ACTIVE_FLEA_ID = "165455"        # Current active league
ACTIVE_FLEA_NAME = "Fleaflicker Main League"
# Restrict active seasons to years the league is actively populated to prevent empty API returns
ACTIVE_SEASONS = ["2024", "2025", "2026"]

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
            
            pf_val = 0.0
            for key in ['fptsFor', 'pointsFor', 'fpts']:
                if key in record and isinstance(record[key], dict):
                    pf_val = float(record[key].get('value', 0.0))
                    break
            
            rank = team.get('rank', 0)
            placement = "🏆 League Champion" if rank == 1 else ("🥈 Runner-Up" if rank == 2 else ("🥉 3rd Place" if rank == 3 else "Regular Season"))
            standings_rows.append([season, mgr_label, f"{wins}-{losses}", f"{pf_val:.2f}", placement, "", ""])
            
    return standings_rows

def sync_fleaflicker():
    if not os.path.exists('sleeper_leagues_master.json'):
        print("sleeper_leagues_master.json not found!")
        return

    with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    # --- PART 1: Safely inject historical 181202 data into Hail Mary Jane Congregation ---
    target_key = None
    for k in master_data.keys():
        if k.strip().lower() == TARGET_LEAGUE_NAME.lower():
            target_key = k
            break

    if target_key:
        print(f"Syncing historical records for {target_key}...")
        existing_rows = master_data[target_key]
        
        # Keep non-historical rows (trades, draft picks, sleeper seasons) intact
        preserved_rows = [r for r in existing_rows if str(r[0] if r else '').strip() not in HISTORICAL_SEASONS]

        new_hist_standings = []
        for season in HISTORICAL_SEASONS:
            new_hist_standings.extend(parse_fleaflicker_standings(season, HISTORICAL_LEAGUE_ID))

        standings_header = ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]

        # Rebuild target league while keeping all trades and drafts safe
        master_data[target_key] = (
            [r for r in preserved_rows if not str(r[0]).upper().startswith('---')] +
            [["", "", "", "", "", "", ""]] +
            [["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""]] +
            [standings_header] +
            new_hist_standings +
            [r for r in preserved_rows if len(r) > 4 or (len(r) == 7 and str(r[1]).startswith("Week"))]
        )

    # --- PART 2: Build Active Fleaflicker League 165455 ---
    print(f"Building master dataset for active Fleaflicker league {ACTIVE_FLEA_ID}...")
    flea_standings = []
    for season in ACTIVE_SEASONS:
        flea_standings.extend(parse_fleaflicker_standings(season, ACTIVE_FLEA_ID))

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
        flea_rosters
    )

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    print("Successfully synchronized Fleaflicker leagues with correct active ranges!")

if __name__ == '__main__':
    sync_fleaflicker()
