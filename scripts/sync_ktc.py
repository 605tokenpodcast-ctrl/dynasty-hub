import json
import sys
import urllib.request

URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams=12&ppr=0.5"

def fetch_values():
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching FantasyCalc values: {e}")
        return []

def main():
    items = fetch_values()
    if not items:
        print("No data returned from FantasyCalc; keeping existing ktc_values.json intact.")
        sys.exit(0)

    players_dict = {}
    for item in items:
        player_obj = item.get('player') or {}
        name = player_obj.get('name')
        value = item.get('value')
        if name and value is not None:
            players_dict[name.strip()] = int(value)

    picks_dict = {
        "1": players_dict.get("2027 1st", 6500),
        "2": players_dict.get("2027 2nd", 3200),
        "3": players_dict.get("2027 3rd", 1500),
        "4": players_dict.get("2027 4th", 750),
        "5": 400,
        "6": 250
    }

    output_data = {
        "picks": picks_dict,
        "players": players_dict
    }

    with open('ktc_values.json', 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"Successfully updated ktc_values.json with {len(players_dict)} entries.")

if __name__ == '__main__':
    main()
