"""Sync player/pick values from FantasyCalc into ktc_values.json.

One FantasyCalc call is made per distinct league format (dynasty vs redraft,
1QB vs superflex, PPR, team count), detected from each Sleeper league's
settings. The output keeps the legacy top-level "players"/"picks" keys
(default dynasty 1QB format) for backwards compatibility and adds:

  formats:        {format_key: {"players": {name: value}, "by_sleeper_id": {id: value}}}
  league_formats: {league_name: format_key}
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_leagues import LEAGUE_IDS, REDRAFT_LEAGUE_IDS  # noqa: E402

OUTPUT = 'ktc_values.json'
DEFAULT_FORMAT = {'isDynasty': True, 'numQbs': 1, 'numTeams': 12, 'ppr': 0.5}
MIN_PLAYERS = 100  # sanity floor: anything smaller is a broken response
PICK_KEY_RE = re.compile(r'^20\d\d \d+(st|nd|rd|th)( \((Early|Mid|Late)\))?$')


def fetch_json(url, retries=4):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            wait = 2 ** (attempt + 1)
            print(f"Fetch failed ({attempt + 1}/{retries}) {url}: {e}; retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Giving up on {url}")


def format_key(fmt):
    kind = 'dynasty' if fmt['isDynasty'] else 'redraft'
    qb = 'sf' if fmt['numQbs'] == 2 else '1qb'
    return f"{kind}_{qb}_ppr{fmt['ppr']:g}_{fmt['numTeams']}t"


def detect_format(league_id):
    league = fetch_json(f"https://api.sleeper.app/v1/league/{league_id}")
    settings = league.get('settings') or {}
    scoring = league.get('scoring_settings') or {}
    positions = league.get('roster_positions') or []

    # Sleeper settings.type: 0 = redraft, 1 = keeper, 2 = dynasty
    is_dynasty = league_id not in REDRAFT_LEAGUE_IDS and settings.get('type', 2) != 0
    num_qbs = 2 if ('SUPER_FLEX' in positions or positions.count('QB') >= 2) else 1
    rec = float(scoring.get('rec', 0.5) or 0)
    ppr = min((0, 0.5, 1), key=lambda p: abs(p - rec))  # FantasyCalc only accepts 0 / 0.5 / 1
    num_teams = int(league.get('total_rosters') or 12)

    fmt = {'isDynasty': is_dynasty, 'numQbs': num_qbs, 'numTeams': num_teams, 'ppr': ppr}
    return league.get('name', league_id).strip(), fmt


def fetch_values(fmt):
    url = (
        "https://api.fantasycalc.com/values/current"
        f"?isDynasty={'true' if fmt['isDynasty'] else 'false'}"
        f"&numQbs={fmt['numQbs']}&numTeams={fmt['numTeams']}&ppr={fmt['ppr']:g}"
    )
    items = fetch_json(url)
    players, by_id = {}, {}
    for item in items or []:
        player_obj = item.get('player') or {}
        name = (player_obj.get('name') or '').strip()
        value = item.get('value')
        if not name or value is None:
            continue
        players[name] = int(value)
        sleeper_id = player_obj.get('sleeperId')
        if sleeper_id:
            by_id[str(sleeper_id)] = int(value)
    if len(players) < MIN_PLAYERS:
        raise RuntimeError(f"FantasyCalc returned only {len(players)} players for {format_key(fmt)}")
    return {'players': players, 'by_sleeper_id': by_id}


def pick_values(players):
    """Fallback value per round for the UI, from the nearest draft class FantasyCalc lists.

    The year is read from the data rather than hardcoded, so the table keeps working after each
    rookie draft (a fixed "2027" would silently fall back to the old 6500/3200 guesses in 2028).
    """
    years = sorted({int(k[:4]) for k in players if PICK_KEY_RE.match(k)})
    year = years[0] if years else None

    def get(rnd, fallback):
        if year is None:
            return fallback
        return players.get(f"{year} {rnd} (Mid)") or players.get(f"{year} {rnd}") or fallback
    return {"1": get('1st', 6500), "2": get('2nd', 3200), "3": get('3rd', 1500),
            "4": get('4th', 750), "5": 400, "6": 250}


def main():
    league_formats = {}
    formats_needed = {format_key(DEFAULT_FORMAT): DEFAULT_FORMAT}
    for league_id in LEAGUE_IDS:
        try:
            name, fmt = detect_format(league_id)
        except RuntimeError as e:
            print(f"Could not read settings for league {league_id}: {e}; using default format")
            continue
        key = format_key(fmt)
        league_formats[name] = key
        formats_needed[key] = fmt
        print(f"{name}: {key}")

    formats = {}
    for key, fmt in formats_needed.items():
        try:
            formats[key] = fetch_values(fmt)
            print(f"Fetched {len(formats[key]['players'])} values for {key}")
        except RuntimeError as e:
            print(f"ERROR: {e}")

    default_key = format_key(DEFAULT_FORMAT)
    if default_key not in formats:
        print("Default format values unavailable; keeping existing ktc_values.json intact.")
        sys.exit(1)

    # Leagues whose format failed to fetch fall back to the default format in the UI
    league_formats = {lg: k for lg, k in league_formats.items() if k in formats}

    output_data = {
        "source": "FantasyCalc",
        "generated_at": int(time.time()),
        "default_format": default_key,
        "picks": pick_values(formats[default_key]['players']),
        "players": formats[default_key]['players'],
        "formats": formats,
        "league_formats": league_formats,
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=1)

    print(f"Updated {OUTPUT}: {len(formats)} formats, {len(league_formats)} leagues mapped.")
    if len(formats) < len(formats_needed):
        sys.exit(1)  # partial data was written, but surface the failure in the workflow


if __name__ == '__main__':
    main()
