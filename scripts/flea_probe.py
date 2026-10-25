"""One-off probe: print sample Fleaflicker API responses (and CORS headers) to the job log.

Used to confirm response shapes for the live scoreboard / boxscore integration. Read-only.
"""
import json
import time
import urllib.request

BASE = "https://www.fleaflicker.com/api/"
LEAGUE = "165455"
ORIGIN = "https://605tokenpodcast-ctrl.github.io"


def get(endpoint, **params):
    q = "&".join(f"{k}={v}" for k, v in {"sport": "NFL", "league_id": LEAGUE, **params}.items())
    req = urllib.request.Request(f"{BASE}{endpoint}?{q}", headers={"User-Agent": "Mozilla/5.0 (dynasty-hub probe)", "Origin": ORIGIN})
    with urllib.request.urlopen(req, timeout=30) as r:
        cors = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")}
        body = json.loads(r.read().decode("utf-8"))
    time.sleep(1.0)
    return body, cors


def show(title, obj, limit=6000):
    print(f"\n===== {title} =====")
    print(json.dumps(obj, indent=1)[:limit])


def key_paths(obj, prefix="", out=None, depth=0):
    """Every distinct key path (lists collapsed to [])."""
    out = set() if out is None else out
    if depth > 9:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(f"{prefix}.{k}")
            key_paths(v, f"{prefix}.{k}", out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:3]:
            key_paths(v, f"{prefix}[]", out, depth + 1)
    return out


board, cors = get("FetchLeagueScoreboard")
print("CORS headers with Origin", ORIGIN, "->", cors or "NONE")
show("scoreboard (current) top-level", {k: v for k, v in board.items() if k != "games"}, 3000)
show("scoreboard (current) games[0]", (board.get("games") or [{}])[0], 4000)
print("\n===== scoreboard key paths =====")
print("\n".join(sorted(key_paths(board))))

future, _ = get("FetchLeagueScoreboard", season=2026, scoring_period=10)
show("scoreboard week 10 games[0]", (future.get("games") or [{}])[0], 2500)

games = board.get("games") or []
if games:
    gid = games[0].get("id")
    period = (board.get("schedulePeriod") or {}).get("value") or (board.get("schedulePeriod") or {}).get("ordinal")
    box, _ = get("FetchLeagueBoxscore", fantasy_game_id=gid, **({"scoring_period": period} if period else {}))
    print("\n===== boxscore key paths =====")
    print("\n".join(sorted(key_paths(box))))
    lineups = box.get("lineups") or []
    show("boxscore top-level (no lineups)", {k: v for k, v in box.items() if k != "lineups"}, 3000)
    if lineups:
        show("boxscore lineups[0] (group + first 2 slots)", {**{k: v for k, v in lineups[0].items() if k != "slots"}, "slots": (lineups[0].get("slots") or [])[:2]}, 7000)

rules, _ = get("FetchLeagueRules")
print("\n===== rules key paths =====")
print("\n".join(sorted(key_paths(rules))[:200]))
