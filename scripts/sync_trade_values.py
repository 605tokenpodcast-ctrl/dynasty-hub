"""Freeze each dynasty trade's dynasty values as of its 3-year grading date into trade_values.json.

The Trade Log grades a dynasty trade 3 years after it happened, partly on what the players (and the
players its picks became) were worth at that point. FantasyCalc only serves today's values, so the
values come from DynastyProcess (github.com/dynastyprocess/data), whose git history keeps a weekly
snapshot of every player and pick value back to 2019:

  - a trade that reaches its 3-year mark is frozen on the next run from the current snapshot;
  - a trade whose mark passed before it was frozen (the backfill, or a missed run) is looked up in the
    snapshot history, which is cloned on demand. Snapshots before June 2020 only carry rankings (ECR),
    so their values are read off the ranking -> value curve of the first snapshot that has both.

Frozen entries are kept, so a trade's grade never moves once set. Redraft leagues are skipped: they
are graded on points alone.

Output: {"source", "trades": {key: {"as_of": "YYYY-MM-DD", "values": {item label: value}}}}
where key = "league||season||date||breakdown" (see tradeValueKey in index.html).
"""
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

OUTPUT = 'trade_values.json'
MASTER = 'sleeper_leagues_master.json'
KTC = 'ktc_values.json'
GRADE_YEARS = 3
DP_REPO = 'https://github.com/dynastyprocess/data.git'
DP_RAW = 'https://raw.githubusercontent.com/dynastyprocess/data/master/files/'
CURRENT_WINDOW_DAYS = 21  # a mark this recent is valued from the current snapshot
EARLIEST_SNAPSHOT = dt.date(2019, 4, 6)  # first DynastyProcess snapshot
REFERENCE_SNAPSHOT = dt.date(2020, 6, 1)  # an early snapshot with both rankings and values
ROUND_SUFFIX = {1: '1st', 2: '2nd', 3: '3rd'}


def normalize_name(name):
    """Same as normalizePlayerName in index.html."""
    s = re.sub(r"[.']", '', str(name or '').lower())
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def trade_rows(rows):
    section = ''
    for r in rows:
        c0 = str(r[0] if r else '').strip()
        if c0.startswith('---'):
            section = 'trades' if 'TRADE HISTORY' in c0 else ''
            continue
        if section == 'trades' and c0 and c0 != 'Season' and len(r) > 4 and r[3] and r[4]:
            yield r


def trade_date(r):
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', str(r[1] or ''))
    if m:
        return dt.date(int(m[3]), int(m[1]), int(m[2]))
    yr = int(r[0]) if str(r[0]).isdigit() else 0
    return dt.date(yr, 1, 1) if yr else None


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def trade_key(league, r):
    return f"{league}||{r[0]}||{r[1]}||{r[4]}"


def trade_items(breakdown):
    """Every received item label, in order, from 'A received: [x, y] <---> B received: [z]'."""
    out = []
    for side in str(breakdown or '').split(' <---> '):
        m = re.match(r'^(.*?) received: \[(.*)\]$', side)
        if m and m[2] != 'Nothing':
            out += [s.strip() for s in re.split(r',\s*(?![^()]*\))', m[2])]
    return out


class Snapshot:
    """One DynastyProcess snapshot: player values by normalized name, pick values by (year, round)."""

    def __init__(self, players_csv, picks_csv, superflex=False, reference_curve=None):
        """reference_curve: ECR -> value pairs for snapshots that only have rankings (before June 2020)."""
        col = 'value_2qb' if superflex else 'value_1qb'
        # 2019 files name the columns mergename / dynoECR / dyno2QBECR
        ecr_cols = ('ecr_2qb', 'dyno2QBECR') if superflex else ('ecr_1qb', 'dynoECR')
        self.players, self.curve = {}, []
        for row in csv.DictReader(io.StringIO(players_csv.lstrip('\ufeff'))):
            ecr, value = ranking(row, ecr_cols), number(row.get(col))
            if value is None and ecr is not None and reference_curve:
                value = interpolate(reference_curve, ecr)
            if value is None:
                continue
            self.players[normalize_name(row.get('player') or row.get('mergename'))] = value
            if ecr is not None:
                self.curve.append((ecr, value))
        self.curve.sort()
        curve = reference_curve if reference_curve and col not in players_csv.split('\n', 1)[0] else self.curve
        # Picks only carry a ranking (ECR); read their value off the players' ECR -> value curve
        self.picks = {}
        for row in csv.DictReader(io.StringIO(picks_csv.lstrip('\ufeff'))):
            name = str(row.get('player') or row.get('mergename') or '').strip()
            # "2026 Pick 1.01", "2027 Early 1st", "2027 1st", and in 2019 "2019 Pick 14" (overall, 12 teams)
            m = re.match(r'^(20\d\d) (?:Pick (\d+)\.\d+|Pick (\d+)|(?:(Early|Mid|Late) )?(\d+)(?:st|nd|rd|th))$', name)
            ecr = ranking(row, ecr_cols)
            if not m or ecr is None:
                continue
            rnd = int(m[2]) if m[2] else (int(m[3]) - 1) // 12 + 1 if m[3] else int(m[5])
            self.picks.setdefault((int(m[1]), rnd), []).append(interpolate(curve, ecr))

    def player(self, name):
        return self.players.get(normalize_name(name), 0)

    def pick(self, year, rnd):
        """Average value of that year's round; nearest listed year when the year itself isn't listed."""
        years = sorted({y for y, r in self.picks if r == rnd}, key=lambda y: (abs(y - year), -y))
        if not years:
            return 0
        vals = self.picks[(years[0], rnd)]
        return sum(vals) / len(vals)


def number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ranking(row, cols):
    for c in cols:
        if number(row.get(c)) is not None:
            return number(row.get(c))
    return None


def interpolate(curve, x):
    if not curve:
        return 0
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def item_value(label, snapshot, as_of):
    """Value of one traded item on the grading date (same item rules as tradeItemPlayerName in index.html)."""
    s = label.strip()
    drafted = re.search(r'Resulted in drafting:\s*(.+?)\s*(?:\([A-Z/]+\))?\s*$', s)
    if drafted:
        return snapshot.player(drafted[1])
    pick = re.match(r'^(\d{4})\s+Round\s+(\d+)', s, re.I)
    if pick:
        year, rnd = int(pick[1]), int(pick[2])
        # Rookie drafts are done by June; a pick from a finished draft with no recorded player is worth nothing
        if as_of >= dt.date(year, 6, 1):
            return 0
        return snapshot.pick(year, rnd)
    m = re.match(r'^(.*?)\s*\(([A-Z/]+)(?:\s*-\s*[A-Z]+)?\)$', s)
    return snapshot.player(m[1] if m else s)


class History:
    """DynastyProcess snapshots by date: the current files, or the git history when a date is older."""

    def __init__(self):
        self.repo = None
        self.commits = None
        self.cache = {}
        self.reference = {}

    def _git(self, *args):
        return subprocess.run(['git', '-C', self.repo, *args], check=True, capture_output=True, text=True).stdout

    def _ensure_repo(self):
        if self.repo:
            return
        self.repo = tempfile.mkdtemp(prefix='dp-')
        subprocess.run(['git', 'clone', '-q', '--filter=blob:none', '--no-checkout', DP_REPO, self.repo], check=True)
        log = self._git('log', '--format=%H %cs', '--', 'files/values-players.csv').split('\n')
        self.commits = sorted((dt.date.fromisoformat(d), h) for h, d in (l.split() for l in log if l.strip()))

    def raw(self, date, today):
        """(as_of date, players csv, picks csv) for the latest snapshot on or before `date`."""
        if (today - date).days <= CURRENT_WINDOW_DAYS:
            return today, fetch_text(DP_RAW + 'values-players.csv'), fetch_text(DP_RAW + 'values-picks.csv')
        self._ensure_repo()
        before = [c for c in self.commits if c[0] <= date]
        if not before:
            return None
        when, commit = before[-1]
        if when not in self.cache:
            show = lambda f: self._git('show', f'{commit}:files/{f}')  # noqa: E731
            self.cache[when] = (when, show('values-players.csv'), show('values-picks.csv'))
        return self.cache[when]


    def reference_curve(self, superflex, today):
        """ECR -> value pairs from the first snapshot that has both, for pre-June-2020 snapshots."""
        if superflex not in self.reference:
            raw = self.raw(REFERENCE_SNAPSHOT, today)
            self.reference[superflex] = Snapshot(raw[1], '', superflex).curve if raw else None
        return self.reference[superflex]


def fetch_text(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode('utf-8')


def due_trades(master, today):
    """(key, league, trade row, grading date) for every dynasty trade whose 3-year mark has passed."""
    redraft = {lg['name'] for lg in league_config.leagues() if lg.get('type') == 'redraft'}
    for league, rows in master.items():
        if league in redraft or not isinstance(rows, list):
            continue
        for r in trade_rows(rows):
            d = trade_date(r)
            if d and add_years(d, GRADE_YEARS) <= today:
                yield trade_key(league, r), league, r, add_years(d, GRADE_YEARS)


def main(today=None):
    today = today or dt.date.today()
    with open(MASTER, encoding='utf-8') as f:
        master = json.load(f)
    try:
        with open(KTC, encoding='utf-8') as f:
            formats = json.load(f).get('league_formats', {})
    except (OSError, ValueError):
        formats = {}
    try:
        with open(OUTPUT, encoding='utf-8') as f:
            frozen = json.load(f).get('trades', {})
    except (OSError, ValueError):
        frozen = {}

    history, snapshots, out, added, skipped = History(), {}, {}, 0, 0
    for key, league, r, mark in due_trades(master, today):
        if key in frozen:
            out[key] = frozen[key]
            continue
        if mark < EARLIEST_SNAPSHOT:
            skipped += 1
            continue
        raw = history.raw(mark, today)
        if not raw:
            skipped += 1
            continue
        superflex = '_sf_' in formats.get(league, '')
        snap_key = (raw[0], superflex)
        if snap_key not in snapshots:
            ref = history.reference_curve(superflex, today) if raw[0] < REFERENCE_SNAPSHOT else None
            snapshots[snap_key] = Snapshot(raw[1], raw[2], superflex, ref)
        snap = snapshots[snap_key]
        out[key] = {'as_of': raw[0].isoformat(), 'values': {lbl: round(item_value(lbl, snap, raw[0])) for lbl in trade_items(r[4])}}
        added += 1

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({'source': 'DynastyProcess', 'trades': dict(sorted(out.items()))}, f, indent=1, ensure_ascii=False)
    print(f"{OUTPUT}: {len(out)} trades ({added} newly frozen, {skipped} too old for value history)")


if __name__ == '__main__':
    main()
