import json
import os
import urllib.request

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
            
            pf_val = 0.0
            for key in ['fptsFor', 'pointsFor', 'fpts']:
                if key in record and isinstance(record[key], dict):
                    pf_val = float(record[key].get('value', 0.0))
                    break
            
            rank = team.get('rank', 0)
            placement = "🏆 League Champion" if rank == 1 else ("🥈 Runner-Up" if rank == 2 else ("🥉 3rd Place" if rank == 3 else "Regular Season"))
            standings_rows.append([season, mgr_label, f"{wins}-{losses}", f"{pf_val:.2f}", placement, "", ""])
            
    return standings_rows

def sync_fleaflicker_active():
    if not os.path.exists('sleeper_leagues_master.json'):
        print("sleeper_leagues_master.json not found!")
        return

    with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    print(f"Building dataset for active Fleaflicker league {ACTIVE_FLEA_ID}...")
    flea_standings = []

    for season in ACTIVE_SEASONS:
        flea_standings.extend(parse_fleaflicker_standings(season, ACTIVE_FLEA_ID))

    flea_rosters = [
        ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
        ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
    ]

    # Safely write or update the standalone Fleaflicker league block without affecting Sleeper leagues
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

    print("Successfully updated active Fleaflicker league while keeping Sleeper leagues and trades intact!")

if __name__ == '__main__':
    sync_fleaflicker_active()
