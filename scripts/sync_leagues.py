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
    
    # 1. Fetch NFL Players dictionary for name mapping
    print("Fetching NFL players database from Sleeper...")
    players_data = fetch_json("https://api.api.app/v1/players/nfl" if False else "https://api.sleeper.app/v1/players/nfl") or {}

    for league_id in LEAGUE_IDS:
        print(f"Processing league ID: {league_id}")
        league_info = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}")
        if not league_info:
            continue
        
        league_name = league_info.get('name', f"League {league_id}")
        rosters = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/rosters") or []
        users = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}/users") or []
        
        user_map = {u['user_id']: u.get('display_name', 'Unknown') for u in users}
        
        # Build structured sheet rows matching your template
        rows = [
            ["--- LEAGUE PROFILE ---", "", "", "", "", "", ""],
            ["League Name", league_name, "", "", "", "", ""],
            ["League ID", league_id, "", "", "", "", ""],
            ["Current Season", league_info.get('season', '2026'), "", "", "", "", ""],
            ["Roster Positions", ", ".join(league_info.get('roster_positions', [])), "", "", "", "", ""]
        ]

        # Standings Section Placeholder / Basic Roster Data mapping
        rows.append(["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""])
        rows.append(["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""])

        for r in rosters:
            owner_id = r.get('owner_id')
            manager_name = user_map.get(owner_id, 'Open Slot')
            settings = r.get('settings', {})
            wins = settings.get('wins', 0)
            losses = settings.get('losses', 0)
            fpts = (settings.get('fpts', 0) or 0) + (settings.get('fpts_decimal', 0) / 100 if settings.get('fpts_decimal') else 0)
            
            # Map player IDs to readable names
            player_strs = []
            for pid in r.get('players', []):
                p_info = players_data.get(pid, {})
                p_name = p_info.get('full_name', pid)
                p_pos = p_info.get('position', 'FLEX')
                p_team = p_info.get('team', 'FA')
                player_strs.append(f"{p_name} ({p_pos} - {p_team})")

            team_label = f"Team ({manager_name})"
            rec_str = f"{wins}-{losses}"
            pf_str = f"{fpts:.2f}"
            roster_str = ", ".join(player_strs)
            
            rows.append([team_label, rec_str, pf_str, roster_str, "2027 Mid Round 1", "", ""])

        master_data[league_name] = rows

    with open('sleeper_leagues_master.json', 'w', encoding='utf-8') as f:
        json.dump(master_data, f, indent=2)
    
    print("Successfully generated sleeper_leagues_master.json directly from Sleeper API!")

if __name__ == '__main__':
    build_master_data()
