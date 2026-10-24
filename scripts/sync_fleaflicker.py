import json
import os
import urllib.request

ACTIVE_FLEA_ID = "165455"
ACTIVE_FLEA_NAME = "Fleaflicker Main League"
# Let's target recent active seasons to verify data population
ACTIVE_SEASONS = ["2024", "2025", "2026"]

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"API Error for {url}: {e}")
        return None

def test_and_sync_fleaflicker():
    if not os.path.exists('sleeper_leagues_master.json'):
        print("sleeper_leagues_master.json not found!")
        return

    with open('sleeper_leagues_master.json', 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    flea_standings = []

    for season in ACTIVE_SEASONS:
        url = f"https://www.fleaflicker.com/api/FetchLeagueStandings?sport=NFL&league_id={ACTIVE_FLEA_ID}&season={season}"
        print(f"Fetching Fleaflicker URL: {url}")
        data = fetch_json(url)
        
        if not data:
            print(f"No data returned for season {season}")
            continue

        # Let's inspect the divisions/teams structure
        divisions = data.get('divisions', [])
        print(f"Found {len(divisions)} divisions for season {season}")

        for div in divisions:
            teams = div.get('teams', [])
            for team in teams:
                team_name = team.get('name', 'Unknown Team')
                owners = team.get('owners', [])
                owner_name = owners[0].get('displayName', 'Unknown Owner') if owners else 'Unknown Owner'
                mgr_label = f"{team_name} ({owner_name})"
                
                # Fleaflicker record parsing handles overall or standard record structures
                record = team.get('record', {})
                wins = record.get('wins', 0)
                losses = record.get('losses', 0)
                
                # Deep check for points for
                pf_val = 0.0
                for pf_key in ['fptsFor', 'pointsFor', 'fpts']:
                    if pf_key in record:
                        val = record[pf_key]
                        if isinstance(val, dict):
                            pf_val = float(val.get('value', 0.0))
                        else:
                            pf_val = float(val or 0.0)
                        break

                rank = team.get('rank', 0)
                placement = "🏆 League Champion" if rank == 1 else ("🥈 Runner-Up" if rank == 2 else ("🥉 3rd Place" if rank == 3 else "Regular Season"))
                
                print(f" -> Parsed Team: {mgr_label} | {wins}-{losses} | PF: {pf_val}")
                flea_standings.append([season, mgr_label, f"{wins}-{losses}", f"{pf_val:.2f}", placement, "", ""])

    flea_rosters = [
        ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
        ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
    ]

    # Write standalone Fleaflicker block into master JSON
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

    print("Fleaflicker sync script completed execution.")

if __name__ == '__main__':
    test_and_sync_fleaflicker()
