"""Temporary: print raw Fleaflicker draft boards and pick trades to the CI log for an accuracy check."""
import json
import sys
sys.path.insert(0, 'scripts')
import sync_fleaflicker as sf

for lid, first, last in [(165455, 2015, 2026), (181202, 2016, 2020)]:
    print(f"## league {lid}")
    for season in range(first, last + 1):
        d = sf.api("FetchLeagueDraftBoard", league_id=lid, season=season) or {}
        top = {k: v for k, v in d.items() if k not in ("rows", "orderedSelections")}
        print(f"BOARD {season} top={json.dumps(top, separators=(',', ':'))[:3000]}")
        cells = [c for r in d.get("rows") or [] for c in r.get("cells") or [] if c] or [c for c in d.get("orderedSelections") or [] if c]
        if cells:
            ex = dict(cells[0]); ex.pop("player", None)
            print(f"CELLKEYS {season} {json.dumps(ex, separators=(',', ':'))[:1500]}")
        for c in cells:
            sl = c.get("slot") or {}
            pro = sf.unwrap_player(c.get("player") or {})
            print(f"C {season}|{sl.get('round')}|{sl.get('slot')}|{sl.get('overall')}|{sf.team_id_of(c.get('team'))}"
                  f"|{int(bool(c.get('fromOtherTeam')))}|{json.dumps({k: v for k, v in c.items() if k not in ('player', 'slot', 'team', 'fromOtherTeam')}, separators=(',', ':'))[:200]}|{pro.get('nameFull')}")
    teams = {}
    for t in sf.fetch_all_trades(lid):
        sides = t.get("teams") or []
        if not any(s.get("picksObtained") for s in sides):
            continue
        out = []
        for s in sides:
            tm = s.get("team") or {}
            teams[str(tm.get("id"))] = tm.get("name")
            picks = [{k: v for k, v in pk.items()} for pk in s.get("picksObtained") or []]
            for pk in picks:
                for k in ("originalOwner", "originalTeam", "ownedBy"):
                    if isinstance(pk.get(k), dict):
                        pk[k] = pk[k].get("id")
            out.append({"team": tm.get("id"), "picks": picks,
                        "players": [sf.unwrap_player(p).get("nameFull") for p in s.get("playersObtained") or []]})
        print("T " + json.dumps({"id": t.get("id"), "at": sf.trade_time(t), "status": t.get("status"),
                                 "sides": out}, separators=(',', ':')))
    print("TEAMS " + json.dumps(teams))
