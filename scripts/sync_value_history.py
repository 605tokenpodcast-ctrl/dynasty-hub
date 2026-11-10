"""Save today's dynasty value of every team into value_history.json, for the Power Rankings value chart.

Each team's value is worked out the same way as the site's Dynasty Value rankings (collectValueTeams
in index.html): every rostered player at the league's FantasyCalc value, plus every future pick at
its pick value. One snapshot is kept per day (US Central), so re-running on the same day replaces it.

  value_history.json: {"days": {"2026-11-10": {league: {manager: [roster value, pick value]}}}}

Run by the daily sync after the value and league syncs. `--backfill` rebuilds past days from the git
history of ktc_values.json and sleeper_leagues_master.json (the last commit of each day).
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

OUTPUT = 'value_history.json'
MASTER = 'sleeper_leagues_master.json'
KTC = 'ktc_values.json'
KEEP_DAYS = 800
PICK_KEY_RE = re.compile(r'^(20\d\d) (\d+)(?:st|nd|rd|th)(?: \((Early|Mid|Late)\))?$')
DEFAULT_PICKS = {"1": 6500, "2": 3200, "3": 1500, "4": 750, "5": 400, "6": 250}


def normalize_name(name):
    """Same as normalizePlayerName in index.html."""
    s = re.sub(r"[.']", '', str(name or '').lower())
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


class ValueFormat:
    """One FantasyCalc format: players by name and normalized name, picks by round -> year -> tier."""

    def __init__(self, players):
        self.players, self.norm, self.picks = players or {}, {}, {}
        for k, v in self.players.items():
            m = PICK_KEY_RE.match(k)
            if m:
                self.picks.setdefault(m[2], {}).setdefault(m[1], {})[m[3] or 'base'] = v
            else:
                self.norm[normalize_name(k)] = v


class Values:
    def __init__(self, ktc):
        self.formats = {k: ValueFormat(f.get('players')) for k, f in (ktc.get('formats') or {}).items()}
        self.default = ktc.get('default_format') or 'default'
        if self.default not in self.formats:
            self.formats[self.default] = ValueFormat(ktc.get('players'))
        self.by_league = {str(k).strip().lower(): v for k, v in (ktc.get('league_formats') or {}).items()}
        self.round_values = {**DEFAULT_PICKS, **(ktc.get('picks') or {})}

    def fmt(self, league):
        return self.formats.get(self.by_league.get(str(league).strip().lower())) or self.formats[self.default]

    def player(self, entry, league):
        """'Kenneth Walker III (RB - SEA)' -> value (scorePlayerKTC)."""
        m = re.match(r'^(.+?)\s*\(([A-Z]+)\s*-\s*([A-Z]+)\)$', str(entry))
        name = (m[1] if m else str(entry)).strip()
        f = self.fmt(league)
        return f.players.get(name) or f.norm.get(normalize_name(name)) or 0

    def pick(self, entry, league):
        """'2027 Mid Round 1' -> value (scoreDraftPickKTC)."""
        s = str(entry)
        rd = re.search(r'Round\s+(\d+)', s, re.I)
        if not rd:
            return 0
        rd = rd[1]
        yr = re.search(r'\b(20\d\d)\b', s)
        tier = re.search(r'\b(Early|Mid|Late)\s+Round', s, re.I)
        tier = tier[1].capitalize() if tier else 'Mid'
        by_year = self.fmt(league).picks.get(rd) or self.formats[self.default].picks.get(rd)
        if by_year:
            years = [int(y) for y in by_year]
            want = int(yr[1]) if yr else min(years)
            best = min(years, key=lambda y: (abs(y - want), years.index(y)))
            slot = by_year[str(best)]
            v = slot.get(tier) or slot.get('Mid') or slot.get('base')
            if v:
                return v
        return self.round_values.get(rd) or 250


def team_values(master, ktc, aliases):
    """{league: {manager: [roster value, pick value]}} from the current rosters."""
    values = Values(ktc)
    out = {}
    for league, rows in master.items():
        if not isinstance(rows, list):
            continue
        section = ''
        for r in rows:
            c0 = str(r[0] if r else '').strip()
            if c0.startswith('---'):
                section = 'rosters' if 'CURRENT ROSTERS' in c0.upper() else ''
                continue
            if section != 'rosters' or not c0 or c0 in ('Team / Manager', 'Season', 'Week', 'League Name'):
                continue
            players = [p.strip() for p in str(r[3] if len(r) > 3 else '').split(',') if p.strip()]
            picks = [p.strip() for p in str(r[4] if len(r) > 4 else '').split(',') if p.strip() and p.strip().lower() != 'none']
            owner = league_config.master_owner(c0, aliases)
            team = out.setdefault(league, {}).setdefault(owner, [0, 0])
            team[0] += round(sum(values.player(p, league) for p in players))
            team[1] += round(sum(values.pick(p, league) for p in picks))
    return out


def central_today():
    return dt.datetime.now(league_config.CENTRAL).date().isoformat()


def load_history():
    try:
        with open(OUTPUT, encoding='utf-8') as f:
            return json.load(f).get('days') or {}
    except (OSError, ValueError):
        return {}


def save_history(days):
    keep = dict(sorted(days.items())[-KEEP_DAYS:])
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({'about': 'Daily dynasty value per team: days -> league -> manager -> [roster, picks]. Written by scripts/sync_value_history.py.',
                   'days': keep}, f, separators=(',', ':'), ensure_ascii=False)
        f.write('\n')


def git_show(sha, path):
    return json.loads(subprocess.run(['git', 'show', f'{sha}:{path}'], capture_output=True, check=True).stdout)


def backfill(days, aliases):
    """One snapshot per Central day from the git history (the day's last commit that has both files)."""
    log = subprocess.run(['git', 'log', '--format=%H %cI', '--', KTC, MASTER], capture_output=True, text=True, check=True).stdout.split('\n')
    per_day = {}
    for line in log:
        if not line.strip():
            continue
        sha, when = line.split()
        day = dt.datetime.fromisoformat(when).astimezone(league_config.CENTRAL).date().isoformat()
        per_day.setdefault(day, sha)   # git log is newest first, so the first one seen is the day's last
    added = 0
    for day, sha in sorted(per_day.items()):
        if day in days:
            continue
        try:
            days[day] = team_values(git_show(sha, MASTER), git_show(sha, KTC), aliases)
            added += 1
        except (subprocess.CalledProcessError, ValueError) as e:
            print(f"  {day}: skipped ({e})")
    print(f"backfilled {added} day(s) from git history")


def main():
    aliases = league_config.manager_aliases()
    days = load_history()
    if '--backfill' in sys.argv:
        backfill(days, aliases)
    with open(MASTER, encoding='utf-8') as f:
        master = json.load(f)
    with open(KTC, encoding='utf-8') as f:
        ktc = json.load(f)
    today = central_today()
    days[today] = team_values(master, ktc, aliases)
    save_history(days)
    print(f"{OUTPUT}: {len(days)} day(s), today {today} has {sum(len(t) for t in days[today].values())} teams")


if __name__ == '__main__':
    main()
