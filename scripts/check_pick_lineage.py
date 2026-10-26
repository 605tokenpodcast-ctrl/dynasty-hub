"""Temporary: rebuild Fleaflicker traded-pick lineage with live data (no file written) and check it
against each receiver's earliest roster in the draft year."""
import json, re, sys
from datetime import datetime
sys.path.insert(0, 'scripts')
import sync_fleaflicker as sf
from league_config import master_owner, manager_aliases

master = json.load(open('sleeper_leagues_master.json'))
A = manager_aliases()
mo = lambda x: master_owner(x, A).lower()  # noqa: E731
SPLIT = re.compile(r',\s*(?![^()\[\]]*[\)\]])')

for lg in sf.league_config.leagues("fleaflicker"):
    name = lg.get("merge_into") or lg["name"]
    key = next(k for k in master if k.strip().lower() == name.strip().lower())
    rows = master[key]
    last = lg.get("end_season") or sf.current_season()
    trades = sf.fetch_all_trades(lg["id"])
    sf.resolve_pick_origins(trades)
    drafted, failed, pickers = sf.fetch_draft_results(lg["id"], trades, lg["start_season"], min(last, sf.current_season()))
    later_moves = []
    if lg.get("merge_into"):
        more, _, more_pickers, later_moves = sf.sleeper_draft_results(lg, trades, last, rows)
        drafted.update(more); pickers.update(more_pickers)
    sf.resolve_pick_origins(trades, pickers, {k[0] for k in pickers}, later_moves)
    fresh = sf.build_trade_rows(trades, {}, {}, drafted)
    sec, idx = '', []
    for i, r in enumerate(rows):
        c = str(r[0])
        if c.startswith('---'): sec = c.upper(); continue
        if 'TRADE' in sec and c and c != 'Season' and int(c) <= last: idx.append(i)
    for i, k in zip(idx, sf.copy_lineage([rows[i] for i in idx], fresh, ())): rows[i] = k

    sec, tr, ros = '', [], {}
    for r in rows:
        c = str(r[0])
        if c.startswith('---'): sec = c.upper(); continue
        if 'TRADE' in sec and c and c != 'Season': tr.append(r)
        if 'LINEUP' in sec and c.isdigit():
            wk = int(re.sub(r'\D', '', str(r[1])) or 0)
            for x in r[3:]:
                for pl in re.findall(r"([A-Z][^;()]*?) \(", str(x)):
                    ros.setdefault((int(c), pl.strip()), []).append((wk, mo(r[2])))
    have = {k[0] for k in ros}
    parsed = []
    for r in tr:
        dt, sides = datetime.strptime(r[1], '%m/%d/%Y'), []
        for side in r[4].split(' <---> '):
            m = re.match(r'^(.*?) received: \[(.*)\]$', side, re.S)
            if m: sides.append((mo(m[1]), [x.strip() for x in SPLIT.split(m[2])]))
        parsed.append((dt, r[1], sides))

    def moved_later(team, yr, rnd, pl, after):
        for dt, _, sides in parsed:
            if dt <= after or team not in [s[0] for s in sides]: continue
            for recv, items in sides:
                if recv != team and any(re.match(rf'{yr} Round {rnd}\D', it) or it.startswith(pl + ' (') for it in items): return True
        return False
    st = {'right': 0, 'wrong': 0, 'unknown': 0, 'blank': 0}
    for dt, d, sides in parsed:
        for recv, items in sides:
            for it in items:
                pm = re.match(r'(\d{4}) Round (\d+)\w* Pick(.*)', it)
                if not pm: continue
                yr, rnd = int(pm[1]), int(pm[2])
                if yr not in have or dt.year > yr or (dt.year == yr and dt.month >= 9): continue
                res = re.search(r'Resulted in drafting: (.+?) \(', pm[3])
                if not res: st['blank'] += 1; print(f"  blank {d} {recv} {yr} R{rnd}"); continue
                pl = res[1]; R = sorted(ros.get((yr, pl), []))
                if not R or moved_later(recv, yr, rnd, pl, dt): st['unknown'] += 1; continue
                if R[0][1] == recv: st['right'] += 1
                else: st['wrong'] += 1; print(f"  WRONG {d} {recv} {yr} R{rnd} -> {pl}; first on roster: wk{R[0][0]} {R[0][1]}")
    print(f"RESULT {name}: {st}")
