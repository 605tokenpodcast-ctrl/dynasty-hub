"""Reality Sports Online (RSO) -> sleeper_leagues_master.json.

RSO has no public API: every page sits behind the league members' login, so this league can't be
synced on a schedule like Sleeper and Fleaflicker. Instead a snapshot of the league's pages is saved
to rso/ (read in a logged-in browser) and this script turns that snapshot into the same sections the
other syncs write, so index.html treats the RSO league like any other league:

  --- LEAGUE PROFILE ---
  --- PAST SEASONS STANDINGS & CHAMPIONS ---     (current season; older RSO seasons are in the history section)
  --- CURRENT ROSTERS & DRAFT PICKS ---
  --- TRADE HISTORY (ALL-TIME & ALL SEASONS) ---
  --- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---
  --- WEEKLY LINEUPS & OPTIMAL SCORES (ALL SEASONS) ---   (RSO gives no per-week lineups; left empty)
  --- WAIVER & FREE AGENT MOVES (ALL SEASONS) ---

plus RSO-only sections the site shows on the Raw League Sheets tab:

  --- PLAYER CONTRACTS (SALARY & YEARS LEFT) ---
  --- SALARY CAP BY TEAM ---
  --- CONTRACT EXTENSIONS & ROOKIE OPTIONS ---
  --- FAAB BIDS (RSO SALARY BIDS) ---
  --- TOP AVAILABLE PLAYERS (FREE AGENTS) ---
  --- RSO LEAGUE HISTORY & PAST CHAMPIONS ---

Run from the repo root after refreshing the files in rso/:  python scripts/build_rso.py
The Sleeper and Fleaflicker syncs keep this block as it is, because they only rewrite their own leagues.
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'rso')
MASTER_FILE = os.path.join(ROOT, 'sleeper_leagues_master.json')

LEAGUE_NAME = 'South Dakota Auction League'
LEAGUE_ID = '3466'
SEASON = 2026
SALARY_CAP = 301_200_000
WEEK1_START = date(2026, 9, 10)   # Thursday of NFL week 1; a week runs Thursday through the next Wednesday
LAST_WEEK = 18

# RSO's abbreviations -> the ones the other leagues use
NFL_TEAM_FIX = {'LA': 'LAR'}

SCORING = {
    'pass_yd': 0.04, 'pass_td': 4, 'pass_int': -2, 'pass_2pt': 2,
    'rush_yd': 0.1, 'rush_td': 6, 'rush_2pt': 2,
    'rec': 0.5, 'rec_yd': 0.1, 'rec_td': 6, 'rec_2pt': 2,
    'fum_lost': -2, 'kr_td': 6, 'pr_td': 6,
}
ROSTER_POSITIONS = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'TE', 'FLEX', 'FLEX', 'SUPER_FLEX'] + ['BN'] * 20

W = 7  # row width used by the other syncs


def pad(row, width=W):
    row = ['' if v is None else str(v) for v in row]
    return row + [''] * (width - len(row))


def read_psv(name):
    with open(os.path.join(SNAP, name), encoding='utf-8') as f:
        lines = [ln.rstrip('\n') for ln in f if ln.strip() and not ln.startswith('#')]
    header = lines[0].split('|')
    # maxsplit: the last column (a transaction description) uses ' || ' between its parts
    return [dict(zip(header, ln.split('|', len(header) - 1))) for ln in lines[1:]]


def money(n):
    return f"${int(round(float(n))):,}"


def fmt_date(d):
    return f"{d.month}/{d.day}/{d.year}"


def parse_ts(ts):
    return datetime.fromisoformat(ts.split('.')[0])


def week_of(d):
    """Week label for a transaction date, matching the Fleaflicker sync (offseason -> Week 1)."""
    days = (d - WEEK1_START).days
    wk = 1 if days < 0 else days // 7 + 1
    return f"Week {min(wk, LAST_WEEK)}"


def nfl(t):
    t = (t or '').strip()
    return NFL_TEAM_FIX.get(t, t)


def clean_player(text):
    """'Michael Wilson ARI (WR)' or 'Smith-Njigba, Jaxon SEA (WR)' -> ('Jaxon Smith-Njigba', 'WR')."""
    text = re.sub(r'\s+', ' ', text.strip())
    m = re.match(r'^(.*?)\s+([A-Z]{2,3})\s+\(([A-Z]+)\)$', text) or re.match(r'^(.*?)\s*\(([A-Z]+)\)$', text)
    if not m:
        return text, ''
    name, pos = (m.group(1), m.group(3)) if m.lastindex == 3 else (m.group(1), m.group(2))
    if ', ' in name:
        last, first = name.split(', ', 1)
        name = f"{first} {last}"
    return name.strip(), pos


def ordinal_pick(text):
    """'2027 2nd Round Draft Pick' -> ('2027', '2nd')."""
    m = re.match(r'^(\d{4}) (\d+(?:st|nd|rd|th)) Round Draft Pick$', text.strip())
    return (m.group(1), m.group(2)) if m else (None, None)


def main():
    teams = {r['teamId']: r for r in read_psv('teams.psv')}
    by_name = {r['team']: r for r in teams.values()}
    label = {tid: f"{r['team']} ({r['handle']})" for tid, r in teams.items()}
    label_by_name = {r['team']: label[tid] for tid, r in teams.items()}

    # ---- standings from the schedule (completed weeks have a non-zero score) ----
    sched = read_psv('schedule.psv')
    rec = {tid: {'w': 0, 'l': 0, 't': 0, 'pf': 0.0} for tid in teams}
    for g in sched:
        a, h = g['awayId'], g['homeId']
        ap, hp = float(g['awayPts']), float(g['homePts'])
        if ap == 0 and hp == 0:
            continue
        rec[a]['pf'] += ap
        rec[h]['pf'] += hp
        if ap > hp:
            rec[a]['w'] += 1; rec[h]['l'] += 1
        elif hp > ap:
            rec[h]['w'] += 1; rec[a]['l'] += 1
        else:
            rec[a]['t'] += 1; rec[h]['t'] += 1
    order = sorted(teams, key=lambda t: (-rec[t]['w'], -rec[t]['pf']))

    def record(t):
        r = rec[t]
        return f"{r['w']}-{r['l']}" + (f"-{r['t']}" if r['t'] else '')

    rows = []

    # ---- profile ----
    rows += [pad(['--- LEAGUE PROFILE ---']),
             pad(['League Name', LEAGUE_NAME]),
             # Not a bare number: index.html reads a 4-9 digit League ID as a Fleaflicker league for live scores
             pad(['League ID', f'RSO {LEAGUE_ID}']),
             pad(['Platform', 'Reality Sports Online']),
             pad(['League Type', 'Dynasty (salary cap, auction contracts)']),
             pad(['Current Season', SEASON]),
             pad(['Roster Positions', ', '.join(ROSTER_POSITIONS)]),
             pad(['Salary Cap', money(SALARY_CAP)]),
             pad(['Playoffs', '6 teams over 3 weeks, weeks 15-17']),
             pad(['Scoring Settings']),
             pad(['', '', '', '', '', json.dumps(json.dumps(SCORING, separators=(',', ':')))]),
             pad([])]

    # ---- standings ----
    rows += [pad(['--- PAST SEASONS STANDINGS & CHAMPIONS ---']),
             pad(['Season', 'Team / Manager', 'Record', 'Points For (PF)', 'Playoff Finish / Placement'])]
    for t in order:
        rows.append(pad([SEASON, label[t], record(t), f"{rec[t]['pf']:.2f}", 'Regular Season']))
    rows.append(pad([]))

    # ---- rosters & picks ----
    roster = defaultdict(list)
    for p in read_psv('roster.psv'):
        roster[p['teamId']].append(f"{p['name']} ({p['pos']} - {nfl(p['nfl'])})")
    picks = defaultdict(list)
    with open(os.path.join(SNAP, 'picks.txt'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln.startswith('# Final Standings'):
                break
            if not ln or ln.startswith('#'):
                continue
            team, rnd, items = ln.split('|')
            for it in filter(None, items.split(';')):
                picks[team].append((it[:4], int(rnd)))
    rows += [pad(['--- CURRENT ROSTERS & DRAFT PICKS ---']),
             pad(['Team / Manager', 'Record', 'Points For (PF)', 'Current Roster (Name Pos Team)', 'Future Draft Picks'])]
    for t in order:
        name = teams[t]['team']
        pk = ', '.join(f"{y} Mid Round {r}" for y, r in sorted(picks[name]))
        rows.append(pad([label[t], record(t), f"{rec[t]['pf']:.2f}", ', '.join(roster[t]), pk]))
    rows.append(pad([]))

    # ---- trades (RSO lists each side separately; pair them by timestamp) ----
    trx = read_psv('transactions.psv')
    trade_groups = defaultdict(list)
    for r in trx:
        if r['type'] == 'Trades':
            trade_groups[r['date'][:19]].append(r)
    trade_rows = []
    for ts, sides in trade_groups.items():
        d = parse_ts(ts)
        got = {}
        for s in sides:
            items = []
            for part in s['description'].split(' || '):
                m = re.match(r'^Received (.+) from (.+)$', part.strip())
                if not m:
                    continue
                what, frm = m.group(1), m.group(2).strip()
                yr, rd = ordinal_pick(what)
                if yr:
                    items.append(f"{yr} Round {rd} Pick (originally from {label_by_name.get(frm, frm)})")
                else:
                    pname, pos = clean_player(what)
                    items.append(f"{pname} ({pos})" if pos else pname)
            got[s['teamId']] = items
        tids = sorted(got, key=int)
        if len(tids) != 2:
            print(f"!! skipped trade at {ts}: {len(tids)} sides")
            continue
        a, b = tids
        breakdown = f"{label[a]} received: [{', '.join(got[a])}] <---> {label[b]} received: [{', '.join(got[b])}]"
        trade_rows.append((d, pad([SEASON, fmt_date(d), week_of(d.date()), f"{label[a]} & {label[b]}", breakdown])))
    trade_rows.sort(key=lambda x: x[0], reverse=True)
    rows += [pad(['--- TRADE HISTORY (ALL-TIME & ALL SEASONS) ---']),
             pad(['Season', 'Date', 'Week', 'Teams Involved', 'Trade Breakdown'])]
    rows += [r for _, r in trade_rows]
    rows.append(pad([]))

    # ---- matchups ----
    rows += [pad(['--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---']),
             pad(['Season', 'Week', 'Matchup ID', 'Team 1', 'Team 1 Score', 'Team 2', 'Team 2 Score'])]
    for g in sched:
        rows.append([str(SEASON), f"Week {g['week']}", g['matchup'], label[g['awayId']], f"{float(g['awayPts']):.2f}",
                     label[g['homeId']], f"{float(g['homePts']):.2f}"])
    rows.append(pad([]))

    # ---- lineups (not available from RSO) ----
    rows += [pad(['--- WEEKLY LINEUPS & OPTIMAL SCORES (ALL SEASONS) ---']),
             pad(['Season', 'Week', 'Team / Manager', 'Score', 'Optimal Score', 'Starters (Name (Pos) Pts)', 'Bench (Name (Pos) Pts)']),
             pad([])]

    # ---- waiver & free agent moves ----
    faab_added = set()
    for b in read_psv('faab.psv'):
        m = re.match(r'^Added (.+?), Dropped', b['claim']) or re.match(r'^Added (.+)$', b['claim'])
        if m and b['won'] == 'true':
            faab_added.add((b['team'].strip(), m.group(1).strip()))
    move_rows = []
    for r in trx:
        if r['type'] != 'Acquisitions':
            continue
        d = parse_ts(r['date'])
        added, dropped = [], []
        for part in r['description'].split(' || '):
            part = part.strip()
            for prefix, bucket in (('Add Player to Roster ', added), ('Added ', added), ('Dropped ', dropped)):
                if part.startswith(prefix):
                    pname, pos = clean_player(part[len(prefix):])
                    bucket.append(f"{pname} ({pos})" if pos else pname)
                    break
        team = teams[r['teamId']]['team']
        is_waiver = any((team, a.rsplit(' (', 1)[0]) in faab_added for a in added)
        move_rows.append((d, [str(SEASON), week_of(d.date()), fmt_date(d), label[r['teamId']],
                              'Waiver' if is_waiver else 'Free Agent', ', '.join(added), ', '.join(dropped), '']))
    move_rows.sort(key=lambda x: x[0], reverse=True)
    rows += [pad(['--- WAIVER & FREE AGENT MOVES (ALL SEASONS) ---'], 8),
             ['Season', 'Week', 'Date', 'Team / Manager', 'Type', 'Added', 'Dropped', 'FAAB Bid']]
    rows += [r for _, r in move_rows]
    rows.append(pad([]))

    # ---- RSO-only: contracts ----
    contracts = read_psv('contracts.psv')
    years = [y for y in ('2026', '2027', '2028', '2029', '2030')]
    tid_order = {t: i for i, t in enumerate(order)}
    contracts.sort(key=lambda c: (tid_order[by_name[c['team'].strip()]['teamId']], -float(c['2026'] or 0)))
    rows += [pad(['--- PLAYER CONTRACTS (SALARY & YEARS LEFT) ---'], 11),
             ['Team / Manager', 'Player (Pos)', f'{SEASON} Salary', 'Years Left', 'Contract Length', 'Total Value',
              'Remaining Value', '2027', '2028', '2029', '2030']]
    for c in contracts:
        left = sum(1 for y in years if c.get(y) and c[y] != 'FA')
        rows.append([label_by_name[c['team'].strip()], f"{c['player']} ({c['pos']})", money(c['2026']), str(left),
                     c['length'], money(c['total']), money(c['remaining'])] +
                    [money(c[y]) if c.get(y) and c[y] != 'FA' else (c.get(y) or '') for y in years[1:]])
    rows.append(pad([], 11))

    # ---- RSO-only: cap by team ----
    committed = defaultdict(lambda: defaultdict(float))
    for c in contracts:
        for y in years:
            if c.get(y) and c[y] != 'FA':
                committed[c['team'].strip()][y] += float(c[y])
    rows += [pad(['--- SALARY CAP BY TEAM ---']),
             pad(['Team / Manager', f'{SEASON} Committed', f'{SEASON} Cap', f'{SEASON} Cap Space', '2027 Committed', '2028 Committed', 'Players Under Contract'])]
    for t in order:
        n = teams[t]['team']
        cm = committed[n]
        count = sum(1 for c in contracts if c['team'].strip() == n)
        rows.append(pad([label[t], money(cm['2026']), money(SALARY_CAP), money(SALARY_CAP - cm['2026']),
                         money(cm['2027']), money(cm['2028']), count]))
    rows.append(pad([]))

    # ---- RSO-only: extensions ----
    rows += [pad(['--- CONTRACT EXTENSIONS & ROOKIE OPTIONS ---']),
             pad(['Season', 'Date', 'Team / Manager', 'Player (Pos)', 'Detail'])]
    for e in read_psv('extensions.psv'):
        d = parse_ts(e['date'])
        m = re.match(r'^(.*?) for (\d+)yr/\$([\d.]+) (.+)$', e['description'])
        if m:
            pname, pos = clean_player(m.group(4))
            detail = f"{m.group(1)}: {m.group(2)} yr at {money(m.group(3))}"
        else:
            pname, pos, detail = e['description'], '', ''
        rows.append(pad([SEASON, fmt_date(d), label[e['teamId']], f"{pname} ({pos})", detail]))
    rows.append(pad([]))

    # ---- RSO-only: FAAB bids ----
    rows += [pad(['--- FAAB BIDS (RSO SALARY BIDS) ---']),
             pad(['Season', 'Date', 'Team / Manager', 'Claim', 'Bid (1-yr salary)', 'Result'])]
    for b in sorted(read_psv('faab.psv'), key=lambda b: b['bidTime'], reverse=True):
        d = parse_ts(b['bidTime'])
        rows.append(pad([SEASON, fmt_date(d), label_by_name.get(b['team'].strip(), b['team'].strip()), b['claim'],
                         money(b['bid']), b['result']]))
    rows.append(pad([]))

    # ---- RSO-only: free agents ----
    rows += [pad(['--- TOP AVAILABLE PLAYERS (FREE AGENTS) ---']),
             pad(['Player (Pos - Team)', 'Season Pts', 'Avg Pts', '% Owned (RSO)', 'Status', 'Injury'])]
    for p in read_psv('free_agents_top120.psv'):
        rows.append(pad([f"{p['name']} ({p['pos']} - {nfl(p['nfl'])})", p['ytdPts'], p['avgPts'], p['pctOwned'],
                         'Waivers' if p['isWaiver'] == 'true' else 'Free Agent', p['injury']]))
    rows.append(pad([]))

    # ---- RSO-only: history ----
    rows += [pad(['--- RSO LEAGUE HISTORY & PAST CHAMPIONS ---']),
             pad(['Season', 'Team', 'Result'])]
    with open(os.path.join(SNAP, 'history_all.txt'), encoding='utf-8') as f:
        hist = dict(ln.rstrip('\n').split(': ', 1) for ln in f if ': ' in ln)
    for item in hist['Champions'].split('; '):
        yr, team = item.split(' ', 1)
        rows.append(pad([yr, label_by_name.get(team, team), 'League Champion']))
    with open(os.path.join(SNAP, 'picks.txt'), encoding='utf-8') as f:
        final = f.read().split('# Final Standings', 1)[1].splitlines()[1:]
    for ln in final:
        if ln.strip():
            team, seed, place = ln.split('|')
            rows.append(pad(['2025', label_by_name.get(team, team), f"Final standing {place} (playoff seed {seed})"]))
    for key in ('All-time regular season', 'All-time playoffs'):
        for item in hist[key].split('; '):
            team, r = item.rsplit(' ', 1)
            rows.append(pad(['All-time', label_by_name.get(team, team), f"{key.split(' ', 1)[1].capitalize()} record {r}"]))
    rows.append(pad([]))

    with open(MASTER_FILE, encoding='utf-8') as f:
        master = json.load(f)
    master[LEAGUE_NAME] = rows
    with open(MASTER_FILE, 'w', encoding='utf-8') as f:
        json.dump(master, f, separators=(',', ':'))
    print(f"{LEAGUE_NAME}: {len(rows)} rows ({len(trade_rows)} trades, {len(move_rows)} moves, "
          f"{len(sched)} games, {len(contracts)} contracts)")


if __name__ == '__main__':
    sys.exit(main())
