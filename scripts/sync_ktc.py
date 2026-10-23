import json
import urllib.request

# FantasyCalc API endpoint for current dynasty values (1QB / Half-PPR / 12-team baseline)
URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams=12&ppr=0.5"

def fetch_values():
    req = urllib.request.Request(
        URL, 
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except Exception as e:
        print(f"Error fetching FantasyCalc values: {e}")
        return []

def main():
    items = fetch_values()
    players_dict = {}
    
    for item in items:
        player_obj = item.get('player', {})
        name = player_obj.get('name')
        value = item.get('value')
        if name and value is not None:
            players_dict[name] = int(value)

    # Load existing ktc_values.json or create base template
    output_data = {
        "picks": {
            "1": 6500,
            "2": 3200,
            "3": 1500,
            "4": 750,
            "5": 400,
            "6": 250
        },
        "players": players_dict
    }

    with open('ktc_values.json', 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"Successfully updated ktc_values.json with {len(players_dict)} players.")

if __name__ == '__main__':
    main()
