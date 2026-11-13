"""Score check: compare the scores Auto-Sync just saved against Sleeper's live API.

Runs after the syncs in the Auto-Sync workflow. For every Sleeper league in leagues.json it re-reads
this season's finished weeks from Sleeper and compares them with sleeper_leagues_master.json:
  - every game's two scores (a score more than 0.01 apart is a mismatch)
  - games Sleeper has that the file is missing, and games in the file Sleeper doesn't have
  - each team's season record and Points For in the standings

Only finished weeks are checked (weeks before the profile's "Open Week"), so a game still being
played never counts. Stat corrections Sleeper makes after the sync show up as a mismatch until the
next sync picks them up.

Writes a Markdown report to score_check_report.md (and to the run's summary page) and exits:
  0  everything matches
  1  mismatches found (the workflow opens or updates a GitHub issue with the report)
  2  Sleeper couldn't be reached, so nothing was checked (no issue; the next run tries again)
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

ROOT = league_config.ROOT
MASTER_FILE = os.path.join(ROOT, 'sleeper_leagues_master.json')
REPORT_FILE = os.path.join(ROOT, 'score_check_report.md')
LAST_WEEK = 17      # same as the Sleeper sync: week 17 is every league's last week
TOLERANCE = 0.01    # the file stores scores to 2 decimals
API = "https://api.sleeper.app/v1"


class SleeperDown(Exception):
    pass


def fetch_json(url, retries=3):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:  # noqa: BLE001
            print(f"Fetch failed ({attempt + 1}/{retries}) {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
    raise SleeperDown(url)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def owner_key(label):
    """Sleeper display name from a "Team Name (display)" label (same as sync_leagues.owner_key)."""
    m = re.search(r'\(([^()]*)\)\s*$', str(label))
    return (m.group(1) if m else str(label)).strip().lower()


def team_labels(users, rosters):
    """roster_id -> the label the sync writes ("Team Name (display)" or just the display name)."""
    user_map = {}
    for u in users or []:
        display = (u.get('display_name') or 'Unknown').strip()
        team = ((u.get('metadata') or {}).get('team_name') or '').strip()
        user_map[u.get('user_id')] = f"{team} ({display})" if team and team.lower() != display.lower() else display
    return {r.get('roster_id'): user_map.get(r.get('owner_id'), f"Team {r.get('roster_id')}") for r in rosters or []}


def saved_sections(rows, season):
    """(profile dict, standings rows, matchups by week) for `season` from one league's saved rows."""
    profile, standings, games = {}, [], {}
    sec = None
    for row in rows:
        c0 = str(row[0] if row else '').strip()
        if c0.startswith('---'):
            u = c0.upper()
            sec = ('profile' if 'PROFILE' in u else 'standings' if 'STANDINGS' in u
                   else 'matchups' if 'MATCHUPS' in u else None)
            continue
        if sec == 'profile' and c0:
            profile[c0] = str(row[1] if len(row) > 1 else '').strip()
        elif sec == 'standings' and c0 == season and len(row) > 3:
            standings.append(row)
        elif sec == 'matchups' and c0 == season and len(row) > 6:
            try:
                week = int(str(row[1]).replace('Week', '').strip())
            except ValueError:
                continue
            games.setdefault(week, []).append(row)
    return profile, standings, games


def finished_weeks(profile):
    """Weeks whose games are all final: before the open week, or every week when no week is open."""
    open_wk = profile.get('Open Week', '').strip()
    last = int(open_wk) - 1 if open_wk.isdigit() else LAST_WEEK
    return list(range(1, min(last, LAST_WEEK) + 1))


def live_games(matchups, labels):
    """[(matchup_id, {owner_key: (label, points)})] for real games (two teams sharing a matchup ID)."""
    by_id = {}
    for m in matchups or []:
        mid = m.get('matchup_id')
        if not mid:
            continue   # a bye or an eliminated team, which the sync doesn't save either
        label = labels.get(m.get('roster_id'), f"Team {m.get('roster_id')}")
        by_id.setdefault(str(mid), {})[owner_key(label)] = (label, float(m.get('points') or 0.0))
    return [(mid, teams) for mid, teams in sorted(by_id.items(), key=lambda kv: int(kv[0])) if len(teams) == 2]


def compare_week(week, saved_rows, live):
    """Problems (strings) for one week: score mismatches, missing games and extra games."""
    problems = []
    saved = {}
    for r in saved_rows:
        saved[str(r[2]).strip()] = {owner_key(r[3]): (r[3], num(r[4])), owner_key(r[5]): (r[5], num(r[6]))}
    for mid, teams in live:
        got = saved.pop(mid, None)
        names = ' vs '.join(lbl for lbl, _ in teams.values())
        if got is None or set(got) != set(teams):
            problems.append(f"Week {week}: game {names} is missing from the saved data")
            if got is not None:
                saved[mid] = got   # keep it so it's reported as an extra game too
            continue
        for key, (label, pts) in teams.items():
            have = got[key][1]
            if have is None or abs(have - pts) > TOLERANCE:
                problems.append(f"Week {week}: {label} saved {got[key][0] if have is None else f'{have:.2f}'}, "
                                f"Sleeper says {pts:.2f}")
    for mid, teams in saved.items():
        names = ' vs '.join(lbl for lbl, _ in teams.values())
        problems.append(f"Week {week}: saved game {names} (matchup {mid}) isn't on Sleeper")
    return problems


def compare_standings(saved_rows, rosters, labels):
    """Problems for each team's season record and Points For."""
    problems = []
    saved = {owner_key(r[1]): r for r in saved_rows}
    for r in rosters or []:
        label = labels.get(r.get('roster_id'), '')
        s = r.get('settings') or {}
        record = league_config.record_str(s.get('wins', 0), s.get('losses', 0), s.get('ties', 0) or 0)
        pf = (s.get('fpts', 0) or 0) + ((s.get('fpts_decimal', 0) or 0) / 100.0)
        row = saved.get(owner_key(label))
        if row is None:
            problems.append(f"Standings: {label} is missing")
            continue
        if str(row[2]).strip() != record:
            problems.append(f"Standings: {label} record saved {row[2]}, Sleeper says {record}")
        have = num(row[3])
        if have is None or abs(have - pf) > TOLERANCE:
            problems.append(f"Standings: {label} Points For saved {row[3]}, Sleeper says {pf:.2f}")
    return problems


def check_league(cfg, master, fetch=fetch_json):
    """(league name, weeks checked, problems, note) for one Sleeper league."""
    name = cfg['name']
    key = next((k for k in master if k.strip().lower() == name.strip().lower()), None)
    if key is None:
        return name, [], [], "not in the saved data yet"
    league_id = cfg['id']
    info = fetch(f"{API}/league/{league_id}") or {}
    season = str(info.get('season') or '').strip()
    profile, standings, games = saved_sections(master[key], season)
    if profile.get('Current Season', '') != season or profile.get('League ID', '') != str(league_id):
        return name, [], [], f"saved data is for another season or league ID, skipped (Sleeper season {season})"
    weeks = finished_weeks(profile)
    rosters = fetch(f"{API}/league/{league_id}/rosters") or []
    users = fetch(f"{API}/league/{league_id}/users") or []
    labels = team_labels(users, rosters)
    problems = []
    for week in weeks:
        live = live_games(fetch(f"{API}/league/{league_id}/matchups/{week}"), labels)
        problems += compare_week(week, games.get(week, []), live)
    problems += compare_standings(standings, rosters, labels)
    return name, weeks, problems, ""


def build_report(results):
    bad = [r for r in results if r[2]]
    lines = ["## Score check against Sleeper", ""]
    if not bad:
        lines.append("All saved scores match Sleeper. ✅")
    else:
        total = sum(len(r[2]) for r in bad)
        lines.append(f"Found **{total}** difference(s) between the site's saved scores and Sleeper.")
    lines.append("")
    for name, weeks, problems, note in results:
        span = f"weeks 1-{weeks[-1]}" if weeks else "no finished weeks"
        if note:
            lines.append(f"- **{name}**: {note}")
        elif not problems:
            lines.append(f"- **{name}**: {span} match ✅")
        else:
            lines.append(f"- **{name}** ({span}): {len(problems)} difference(s)")
            lines += [f"  - {p}" for p in problems[:40]]
            if len(problems) > 40:
                lines.append(f"  - ...and {len(problems) - 40} more")
    if bad:
        lines += ["", "**What to do:** usually nothing. Sleeper's Tuesday/Thursday stat corrections land after a "
                  "sync, and the next Auto-Sync picks them up; this issue closes itself once a check passes. "
                  "If the same difference shows up two runs in a row, run Auto-Sync by hand "
                  "(Actions → Auto-Sync Dynasty Hub Data → Run workflow). If it's still there after that, "
                  "the sync has a bug worth a look."]
    return "\n".join(lines) + "\n"


def main():
    with open(MASTER_FILE, 'r', encoding='utf-8') as f:
        master = json.load(f)
    results = []
    try:
        for cfg in league_config.leagues('sleeper'):
            results.append(check_league(cfg, master))
    except SleeperDown as e:
        print(f"Sleeper couldn't be reached ({e}); score check skipped this run.")
        return 2
    report = build_report(results)
    print(report)
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write(report)
    return 1 if any(r[2] for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
