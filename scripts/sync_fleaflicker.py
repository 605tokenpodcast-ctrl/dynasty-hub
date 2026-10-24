import json
import os
import urllib.request

LEAGUES_TO_SYNC = [
    {
        "id": "165455",
        "name": "Fleaflicker Main League",
        "type": "dynasty",
        "seasons": ["2024", "2025", "2026"]
    }
]

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"API Error for {url}: {e}")
        return None

def parse_fleaflicker_standings(season, league_id):
    standings_rows = []
    url = f"https://www.fleaflicker.com/api/FetchLeagueStandings?sport=NFL&league_id={league_id}&season={season}"
    data = fetch_json(url)
    if not data:
        return standings_rows

    for div in data.get('divisions', []):
        for team in div.get('teams', []):
            team_name = team.get('name', 'Team')
            owners = team.get('owners', [])
            owner_name = owners[0].get('displayName', 'Owner') if owners else 'Owner'
            mgr_label = f"{team_name} ({owner_name})"
            
            # Correctly access nested overall record object
            record_container = team.get('record', {})
            rec_obj = record_container.get('overall', record_container)

            wins = rec_obj.get('wins', 0)
            losses = rec_obj.get('losses', 0)
            
            pf_val = 0.0
            for pf_key in ['fptsFor', 'pointsFor', 'fpts']:
                val = rec_obj.get(pf_key) or record_container.get(pf_key)
                if val:
                    if isinstance(val, dict):
                        pf_val = float(val.get('value', 0.0))
                    else:
                        pf_val = float(val or 0.0)
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

    for league in LEAGUES_TO_SYNC:
        league_id = league["id"]
        league_name = league["name"]
        league_type = league["type"]
        seasons = league["seasons"]

        flea_standings = []
        for season in seasons:
            flea_standings.extend(parse_fleaflicker_standings(season, league_id))

        league_blocks = [
            ["--- LEAGUE PROFILE ---", "", "", "", "", "", ""],
            ["League Name", league_name, "", "", "", "", ""],
            ["League ID", league_id, "", "", "", "", ""],
            ["League Type", league_type.capitalize(), "", "", "", "", ""],
            ["Current Season", "2026", "", "", "", "", ""]
        ] + [["", "", "", "", "", "", ""]] + [
            ["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""],
            ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""]
        ] + flea_standings

        if league_type == "dynasty":
            league_blocks += [["", "", "", "", "", "", ""]] + [
                ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
                ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""]
            ]

        master_data[league_name] = league_blocks

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, separators=(',', ':'))

    print("Fleaflicker sync completed.")

if __name__ == '__main__':
    sync_fleaflicker()
