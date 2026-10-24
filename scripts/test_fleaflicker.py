import json
import urllib.request

def fetch_fleaflicker(endpoint, params=""):
    url = f"https://www.fleaflicker.com/api/{endpoint}?sport=NFL&{params}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching {endpoint}: {e}")
        return None

def test_leagues():
    historical_id = "181202"  # 2016-2020 history
    current_id = "165455"      # 2015-Present active
    
    print("=== TESTING HISTORICAL LEAGUE (181202) FOR 2020 ===")
    data = fetch_fleaflicker("FetchLeagueStandings", f"league_id={historical_id}&season=2020")
    if data:
        print("SUCCESS! Found historical league data for 2020:")
        for div in data.get('divisions', []):
            for team in div.get('teams', []):
                name = team.get('name')
                owners = [o.get('displayName') for o in team.get('owners', [])]
                record = team.get('record', {})
                print(f" -> Team: {name} | Owners: {owners} | Record: {record.get('wins')}-{record.get('losses')}")
    else:
        print("Could not fetch league 181202.")

    print("\n=== TESTING ACTIVE LEAGUE (165455) ===")
    data_curr = fetch_fleaflicker("FetchLeagueStandings", f"league_id={current_id}&season=2026")
    if data_curr:
        print("SUCCESS! Found active league 165455 for 2026 season!")
    else:
        print("Tried 2026 for active league, trying without season parameter...")
        data_curr_fallback = fetch_fleaflicker("FetchLeagueStandings", f"league_id={current_id}")
        if data_curr_fallback:
            print("SUCCESS! Found active league 165455 on fallback query!")
        else:
            print("Could not reach active league 165455.")

if __name__ == '__main__':
    test_leagues()
