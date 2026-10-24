"""
Fleaflicker -> sleeper_leagues_master.json sync.

Builds the same sections the Sleeper sync produces, so index.html treats the
Fleaflicker league like any other league:

  --- LEAGUE PROFILE ---
  --- PAST SEASONS STANDINGS & CHAMPIONS ---     (every season since START_SEASON)
  --- CURRENT ROSTERS & DRAFT PICKS ---
  --- TRADE HISTORY (ALL-TIME & ALL SEASONS) --- (every completed trade)
  --- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) --- (every game, every season)

Set FLEA_DEBUG=1 to also dump the first raw response of every endpoint into
./fleaflicker_debug/ (the workflow uploads that folder as a build artifact).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

LEAGUES_TO_SYNC = [
    {
        "id": "165455",
        "name": "Branden's League",
        "type": "dynasty",
        "start_season": 2015,
    },
    {
        # Ran on Fleaflicker 2016-2020, then moved to Sleeper. Its history is spliced
        # into the existing Sleeper block (key below) instead of getting its own block.
        "id": "181202",
        "name": "Hail Mary Jane Congregation (Fleaflicker era)",
        "type": "dynasty",
        "start_season": 2016,
        "end_season": 2020,
        "merge_into": "Hail Mary Jane Congregation",
    }
]

MASTER_FILE = "sleeper_leagues_master.json"
API_BASE = "https://www.fleaflicker.com/api/"
REQUEST_DELAY = 0.8           # seconds between calls - Fleaflicker answers HTTP 403 if you go faster
RETRY_BACKOFF = [5, 20, 60, 120]   # seconds to wait before each retry of a refused/failed call
SEASON_RETRY_COOLDOWN = 150   # extra cooldown before re-trying a season that failed outright
MAX_SCORING_PERIODS = 20      # upper bound if the API doesn't tell us
FALLBACK_REG_SEASON_WEEKS = 14
FUTURE_PICK_SEASONS = 3       # how many upcoming draft classes to list per team
DEBUG = os.environ.get("FLEA_DEBUG") == "1"
DEBUG_DIR = "fleaflicker_debug"

# If the automatic champion / runner-up / 3rd-place detection ever gets a season
# wrong (e.g. two-week championship), pin it here by Fleaflicker team id:
#   PLACEMENT_OVERRIDES = {"2019": {"champion": 123456, "runner_up": 234567, "third": 345678}}
PLACEMENT_OVERRIDES = {}

BLANK = ["", "", "", "", "", "", ""]
_debug_seen = set()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def current_season():
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


def ordinal(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]}"


def num(x, default=0.0):
    """Fleaflicker wraps numbers as {"value": 1.0, "formatted": "1"}."""
    if isinstance(x, dict):
        x = x.get("value", x.get("formatted"))
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return default


class FleaError(Exception):
    """A call kept failing after all retries (rate limit, outage...). Distinct from 'no such season'."""


def api(endpoint, **params):
    query = {"sport": "NFL"}
    query.update({k: v for k, v in params.items() if v is not None})
    url = API_BASE + endpoint + "?" + urllib.parse.urlencode(query)
    data = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dynasty-hub sync)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):      # season/league doesn't exist - not worth retrying
                print(f"  {endpoint} {params}: HTTP {e.code}")
                return None
            print(f"  {endpoint} {params}: HTTP {e.code} (attempt {attempt + 1})")
        except Exception as e:  # network hiccup, bad JSON...
            print(f"  {endpoint} {params}: {e} (attempt {attempt + 1})")
        if attempt < len(RETRY_BACKOFF):
            time.sleep(RETRY_BACKOFF[attempt])
    else:
        raise FleaError(f"{endpoint} {params} kept failing")
    time.sleep(REQUEST_DELAY)
    dbg_key = (endpoint, params.get("league_id"))
    if data is not None and DEBUG and dbg_key not in _debug_seen:
        _debug_seen.add(dbg_key)
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"{endpoint}_{params.get('league_id', '')}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
            f.write("\n")
    return data


def team_label(team):
    """'Team Name (OwnerName)' - same shape the Sleeper sync uses."""
    team = team or {}
    name = (team.get("name") or "").strip()
    owners = team.get("owners") or []
    display = ((owners[0] or {}).get("displayName") or "").strip() if owners else ""
    if name and display and name.lower() != display.lower():
        return f"{name} ({display})"
    return name or display or f"Team {team.get('id', '?')}"


def player_label(pro, with_team=False):
    pro = pro or {}
    name = pro.get("nameFull") or f"{pro.get('nameFirst', '')} {pro.get('nameLast', '')}".strip() or "Unknown"
    pos = pro.get("position") or "FLEX"
    if with_team:
        return f"{name} ({pos} - {pro.get('proTeamAbbreviation') or 'FA'})"
    return f"{name} ({pos})"


def unwrap_player(p):
    """Trade/roster entries nest the player a few different ways."""
    p = p or {}
    for key in ("proPlayer",):
        if key in p:
            return p[key]
    lp = p.get("leaguePlayer")
    if isinstance(lp, dict):
        return lp.get("proPlayer") or lp
    return p


def epoch_to_dt(raw):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v < 1e11:      # seconds, not ms
        v *= 1000.0
    return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)


def nfl_kickoff(season):
    d = date(season, 9, 1)
    while d.weekday() != 0:       # Labor Day = first Monday in September
        d += timedelta(days=1)
    return d + timedelta(days=3)  # Thursday night opener


def season_and_week(dt):
    """Season a trade belongs to + NFL week (offseason = Week 1, matches Sleeper rows)."""
    season = dt.year if dt.month >= 3 else dt.year - 1
    kickoff = nfl_kickoff(season)
    if dt.date() < kickoff:
        week = 1
    else:
        week = min(18, (dt.date() - kickoff).days // 7 + 1)
    return season, week


# --------------------------------------------------------------------------- #
# standings + scoreboard (one season)
# --------------------------------------------------------------------------- #
def fetch_standings(league_id, season):
    data = api("FetchLeagueStandings", league_id=league_id, season=season)
    if not data:
        return []
    teams = []
    divisions = data.get("divisions") or []
    for div in divisions:
        teams.extend(div.get("teams") or [])
    if not teams:
        teams = data.get("teams") or []

    out = []
    for t in teams:
        rec = t.get("recordOverall") or (t.get("record") or {}).get("overall") or t.get("record") or {}
        out.append({
            "id": t.get("id"),
            "label": team_label(t),
            "wins": int(num(rec.get("wins"))),
            "losses": int(num(rec.get("losses"))),
            "ties": int(num(rec.get("ties"))),
            "pf": num(t.get("pointsFor") if t.get("pointsFor") is not None else rec.get("pointsFor")),
            "api_rank": int(num(rec.get("rank"), 0)),
        })
    return out


def fetch_scoreboard(league_id, season):
    """Returns {period: [game, ...]} with normalised games."""
    periods = {}
    seen_ids = set()
    max_period = MAX_SCORING_PERIODS
    for p in range(1, MAX_SCORING_PERIODS + 1):
        if p > max_period:
            break
        data = api("FetchLeagueScoreboard", league_id=league_id, season=season, scoring_period=p)
        if not data:
            break
        if p == 1:
            ordinals = [int(num(e.get("ordinal"), 0)) for e in (data.get("eligibleSchedulePeriods") or [])]
            if ordinals:
                max_period = max(ordinals)
        games = []
        for g in data.get("games") or []:
            home, away = g.get("home") or {}, g.get("away") or {}
            if not home.get("id") or not away.get("id"):
                continue  # bye
            hs = num((g.get("homeScore") or {}).get("score", g.get("homeScore")))
            as_ = num((g.get("awayScore") or {}).get("score", g.get("awayScore")))
            final = bool(g.get("isFinalScore") or g.get("isFinal"))
            if not final and hs == 0 and as_ == 0:
                continue  # not played yet
            games.append({
                "gid": str(g.get("id")),
                "home": home, "away": away,
                "hs": hs, "as": as_, "final": final,
            })
        ids = {g["gid"] for g in games}
        if not games or ids <= seen_ids:
            break
        seen_ids |= ids
        periods[p] = games
    return periods


def rank_teams(rows):
    rows.sort(key=lambda r: (-r["wins"], r["losses"], -r["pf"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def infer_placements(season, rows, periods, reg_weeks):
    """champion / runner_up / third -> team id. Needs finished playoff weeks."""
    ov = PLACEMENT_OVERRIDES.get(str(season))
    if ov:
        return ov
    rank = {r["id"]: r["rank"] for r in rows}
    playoff_periods = sorted(p for p in periods if p > reg_weeks)
    if not playoff_periods:
        return {}
    last = playoff_periods[-1]
    last_games = periods[last]
    if not all(g["final"] for g in last_games):
        return {}  # season still in progress

    def winner_loser(g):
        if g["hs"] == g["as"]:
            return None, None
        return (g["home"]["id"], g["away"]["id"]) if g["hs"] > g["as"] else (g["away"]["id"], g["home"]["id"])

    prev_w, prev_l = set(), set()
    if len(playoff_periods) > 1:
        for g in periods[playoff_periods[-2]]:
            w, l = winner_loser(g)
            if w is not None:
                prev_w.add(w)
                prev_l.add(l)

    def strength(g):
        return rank.get(g["home"]["id"], 99) + rank.get(g["away"]["id"], 99)

    if prev_w:
        champ_c = [g for g in last_games if g["home"]["id"] in prev_w and g["away"]["id"] in prev_w]
        third_c = [g for g in last_games if g["home"]["id"] in prev_l and g["away"]["id"] in prev_l]
    else:
        champ_c, third_c = list(last_games), []
    if not champ_c:
        champ_c = list(last_games)

    champ_game = min(champ_c, key=strength)
    w, l = winner_loser(champ_game)
    if w is None:
        return {}
    result = {"champion": w, "runner_up": l}
    third_c = [g for g in third_c if g is not champ_game]
    if third_c:
        w3, _ = winner_loser(min(third_c, key=strength))
        if w3 is not None:
            result["third"] = w3
    return result


def build_season(league_id, season):
    rows = fetch_standings(league_id, season)
    if not rows:
        return None
    periods = fetch_scoreboard(league_id, season)

    # --- safety net: if the standings payload carried no usable record/PF,
    # rebuild them from the scoreboard (regular-season weeks only).
    if rows and not any(r["wins"] + r["losses"] + r["ties"] for r in rows) and periods:
        print(f"  {season}: standings had no records, deriving from scoreboard")
        by_id = {r["id"]: r for r in rows}
        for p, games in periods.items():
            if p > FALLBACK_REG_SEASON_WEEKS:
                continue
            for g in games:
                if not g["final"]:
                    continue
                for tid, mine, theirs in ((g["home"]["id"], g["hs"], g["as"]), (g["away"]["id"], g["as"], g["hs"])):
                    r = by_id.get(tid)
                    if not r:
                        continue
                    r["pf"] += mine
                    if mine > theirs:
                        r["wins"] += 1
                    elif mine < theirs:
                        r["losses"] += 1
                    else:
                        r["ties"] += 1

    rank_teams(rows)
    reg_weeks = max((r["wins"] + r["losses"] + r["ties"] for r in rows), default=0) or FALLBACK_REG_SEASON_WEEKS
    placements = infer_placements(season, rows, periods, reg_weeks)
    return {"rows": rows, "periods": periods, "reg_weeks": reg_weeks, "placements": placements}


def placement_label(team_id, placements):
    if placements.get("champion") == team_id:
        return "🏆 League Champion"
    if placements.get("runner_up") == team_id:
        return "🥈 Runner-Up"
    if placements.get("third") == team_id:
        return "🥉 3rd Place"
    return "Regular Season"


# --------------------------------------------------------------------------- #
# trades
# --------------------------------------------------------------------------- #
def fetch_all_trades(league_id):
    trades, offset, seen_offsets = [], None, set()
    for _ in range(300):
        data = api("FetchTrades", league_id=league_id, filter="TRADES_COMPLETED", result_offset=offset)
        if not data:
            break
        trades.extend(data.get("trades") or [])
        nxt = data.get("resultOffsetNext")
        if nxt is None or nxt in seen_offsets:
            break
        seen_offsets.add(nxt)
        offset = nxt
    return trades


def build_trade_rows(trades, season_labels, latest_label):
    def label_for(team, season):
        tid = (team or {}).get("id")
        return season_labels.get(season, {}).get(tid) or latest_label.get(tid) or team_label(team)

    rows = []
    for t in trades:
        dt = epoch_to_dt(t.get("approvedOn") or t.get("tradeTime") or t.get("createdOn"))
        if not dt:
            continue
        season, week = season_and_week(dt)
        sides = t.get("teams") or []
        if len(sides) < 2:
            continue

        teams_involved = " & ".join(label_for(s.get("team"), season) for s in sides)
        parts = []
        for s in sides:
            mgr = label_for(s.get("team"), season)
            items = []
            for p in s.get("playersObtained") or []:
                items.append(player_label(unwrap_player(p)))
            for pk in s.get("picksObtained") or []:
                slot = pk.get("slot") or {}
                rnd = slot.get("round") or pk.get("round") or 1
                desc = f"{pk.get('season', '')} Round {ordinal(rnd)} Pick"
                orig = pk.get("originalOwner") or pk.get("originalTeam")
                if orig:
                    desc += f" (originally from {label_for(orig, season)})"
                items.append(desc.strip())
            parts.append(f"{mgr} received: [{', '.join(items) if items else 'Nothing'}]")

        date_str = f"{dt.month}/{dt.day}/{dt.year}"
        rows.append((dt, [str(season), date_str, f"Week {week}", teams_involved, " <---> ".join(parts), "", ""]))

    rows.sort(key=lambda x: x[0], reverse=True)   # newest first, like the Sleeper block
    return [r for _, r in rows]


# --------------------------------------------------------------------------- #
# rosters + picks (current season only)
# --------------------------------------------------------------------------- #
def fetch_roster_str(league_id, team_id, season):
    try:
        data = api("FetchRoster", league_id=league_id, team_id=team_id, season=season)
    except FleaError:
        return ""
    names = []
    if data:
        for grp in data.get("groups") or []:
            for slot in grp.get("slots") or []:
                lp = slot.get("leaguePlayer")
                if lp:
                    names.append(player_label(unwrap_player(lp), with_team=True))
    return ", ".join(names)


def team_id_of(x):
    """Team id as a string from either a team dict or a bare id (None if missing)."""
    if isinstance(x, dict):
        x = x.get("id")
    return str(x) if x not in (None, "") else None


def pick_key_parts(pk):
    """(year, round, original-owner id) for a pick record from FetchTeamPicks or a trade."""
    yr = int(num(pk.get("season"), 0))
    slot = pk.get("slot") or {}
    rnd = int(num(slot.get("round") or pk.get("round"), 0))
    orig = team_id_of(pk.get("originalOwner") or pk.get("originalTeam") or slot.get("originalOwner"))
    return yr, rnd, orig


def latest_pick_owners(trades):
    """
    Who holds each traded pick right now, according to trade history.
    Key = (year, round, original owner id) -> id of the team that received it in the newest trade.
    """
    latest = {}
    for t in trades:
        dt = epoch_to_dt(t.get("approvedOn") or t.get("tradeTime") or t.get("createdOn"))
        if not dt:
            continue
        for side in t.get("teams") or []:
            recv = team_id_of(side.get("team"))
            for pk in side.get("picksObtained") or []:
                yr, rnd, orig = pick_key_parts(pk)
                if not (yr and rnd and orig and recv):
                    continue
                key = (yr, rnd, orig)
                if key not in latest or dt > latest[key][0]:
                    latest[key] = (dt, recv)
    return {k: v[1] for k, v in latest.items()}


def fetch_team_picks_raw(league_id, team_id, season):
    """Every future pick Fleaflicker lists for a team (it can include picks the team traded away)."""
    try:
        data = api("FetchTeamPicks", league_id=league_id, team_id=team_id)
    except FleaError:
        return []
    out = []
    for pk in (data or {}).get("picks") or []:
        yr, rnd, orig = pick_key_parts(pk)
        if not (rnd and season < yr <= season + FUTURE_PICK_SEASONS):
            continue
        owner = team_id_of(pk.get("ownedBy") or pk.get("owner") or pk.get("currentOwner"))
        out.append({"yr": yr, "rnd": rnd, "orig": orig, "owner": owner})
    return out


def resolve_pick_strings(raw_by_team, trade_owner):
    """
    Keep each pick only on the team that actually holds it now.
    Order of evidence: an explicit owner field on the pick, then the newest trade
    involving that pick, then 'listed by two teams -> the original owner traded it away'.
    """
    listed = {}
    for tid, picks in raw_by_team.items():
        for pk in picks:
            listed.setdefault((pk["yr"], pk["rnd"], pk["orig"] or tid), set()).add(tid)

    result, dropped = {}, 0
    for tid, picks in raw_by_team.items():
        kept = {}
        for pk in picks:
            orig = pk["orig"] or tid
            key = (pk["yr"], pk["rnd"], orig)
            if pk["owner"]:
                keep = pk["owner"] == tid
            elif key in trade_owner:
                keep = trade_owner[key] == tid
            else:
                keep = len(listed[key]) <= 1 or orig != tid
            if keep:
                kept[key] = (pk["yr"], pk["rnd"])
            else:
                dropped += 1
        ordered = sorted(kept.values())
        result[tid] = ", ".join(f"{y} Mid Round {r}" for y, r in ordered) if ordered else "None"
    print(f"  picks: dropped {dropped} listing(s) of picks the team no longer holds")
    return result


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def collect_league(league):
    """Pull standings / matchups / trades (and rosters if it's a live season)."""
    league_id, name = league["id"], league["name"]
    last = league.get("end_season") or current_season()
    cur = current_season()
    print(f"== {name} ({league_id}), seasons {league['start_season']}-{last}")

    standings_rows, matchup_rows = [], []
    season_labels, latest_label = {}, {}
    current_rows = []

    def load_season(season):
        print(f"- season {season}")
        info = build_season(league_id, season)
        if not info:
            print("  no data (league didn't exist for this season)")
            return
        rows, periods, placements = info["rows"], info["periods"], info["placements"]
        season_labels[season] = {r["id"]: r["label"] for r in rows}
        latest_label.update(season_labels[season])
        if season == cur:
            current_rows.extend(rows)

        for r in rows:
            standings_rows.append([
                str(season), r["label"], f"{r['wins']}-{r['losses']}", f"{r['pf']:.2f}",
                placement_label(r["id"], placements), "", "",
            ])

        n_games = 0
        for p in sorted(periods):
            for idx, g in enumerate(periods[p], 1):
                lab = season_labels[season]
                h = lab.get(g["home"]["id"]) or team_label(g["home"])
                a = lab.get(g["away"]["id"]) or team_label(g["away"])
                matchup_rows.append([str(season), f"Week {p}", str(idx), h, f"{g['hs']:.2f}", a, f"{g['as']:.2f}"])
                n_games += 1
        print(f"  {len(rows)} teams, {n_games} games, regular season = {info['reg_weeks']} wks, placements = {placements or 'n/a'}")

    def drop_partial(season):
        s_ = str(season)
        standings_rows[:] = [r for r in standings_rows if r[0] != s_]
        matchup_rows[:] = [r for r in matchup_rows if r[0] != s_]
        season_labels.pop(season, None)

    failed = []
    for season in range(league["start_season"], last + 1):
        try:
            load_season(season)
        except FleaError as e:
            print(f"  !! season {season} failed ({e}); will retry after a cooldown")
            drop_partial(season)
            failed.append(season)

    if failed:
        print(f"Cooling down {SEASON_RETRY_COOLDOWN}s before retrying seasons {failed}")
        time.sleep(SEASON_RETRY_COOLDOWN)
        still = []
        for season in failed:
            try:
                load_season(season)
            except FleaError as e:
                print(f"  !! season {season} failed again ({e})")
                drop_partial(season)
                still.append(season)
        if still:
            raise FleaError(f"{name}: seasons {still} could not be loaded; existing data left untouched")

    if not standings_rows:
        return None

    # newest season first (matches Sleeper block); keep original order inside a season
    standings_rows.sort(key=lambda r: -int(r[0]))
    matchup_rows.sort(key=lambda r: -int(r[0]))

    print("- trades")
    trades = fetch_all_trades(league_id)
    trade_rows = build_trade_rows(trades, season_labels, latest_label)
    # a league that has an end_season must not pick up trades from later seasons
    trade_rows = [t for t in trade_rows if int(t[0]) <= last]
    print(f"  {len(trade_rows)} completed trades")

    roster_rows = []
    if current_rows:
        print("- current rosters & picks")
        raw_picks = {str(r["id"]): fetch_team_picks_raw(league_id, r["id"], cur) for r in current_rows}
        pick_strs = resolve_pick_strings(raw_picks, latest_pick_owners(trades))
        for r in current_rows:
            roster_rows.append([
                r["label"], f"{r['wins']}-{r['losses']}", f"{r['pf']:.2f}",
                fetch_roster_str(league_id, r["id"], cur),
                pick_strs.get(str(r["id"]), "None"),
                "", "",
            ])
    return {"standings": standings_rows, "matchups": matchup_rows, "trades": trade_rows,
            "rosters": roster_rows, "last": last}


def build_standalone_block(league, data):
    cur = current_season()
    return [
        ["--- LEAGUE PROFILE ---", "", "", "", "", "", ""],
        ["League Name", league["name"], "", "", "", "", ""],
        ["League ID", league["id"], "", "", "", "", ""],
        ["League Type", league["type"].capitalize(), "", "", "", "", ""],
        ["Current Season", str(cur), "", "", "", "", ""],
        BLANK,
        ["--- PAST SEASONS STANDINGS & CHAMPIONS ---", "", "", "", "", "", ""],
        ["Season", "Team / Manager", "Record", "Points For (PF)", "Playoff Finish / Placement", "", ""],
    ] + data["standings"] + [
        BLANK,
        ["--- CURRENT ROSTERS & DRAFT PICKS ---", "", "", "", "", "", ""],
        ["Team / Manager", "Record", "Points For (PF)", "Current Roster (Name Pos Team)", "Future Draft Picks", "", ""],
    ] + data["rosters"] + [
        BLANK,
        ["--- TRADE HISTORY (ALL-TIME & ALL SEASONS) ---", "", "", "", "", "", ""],
        ["Season", "Date", "Week", "Teams Involved", "Trade Breakdown", "", ""],
    ] + data["trades"] + [
        BLANK,
        ["--- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) ---", "", "", "", "", "", ""],
        ["Season", "Week", "Matchup ID", "Team 1", "Team 1 Score", "Team 2", "Team 2 Score"],
    ] + data["matchups"]


def merge_into_existing(rows, data, first_season, last_season):
    """
    Splice Fleaflicker-era history into an existing (Sleeper) block.
    Removes any rows already present for those seasons (placeholders or a previous
    run of this script) and appends the fresh ones at the end of each section.
    """
    seasons = {str(y) for y in range(first_season, last_season + 1)}
    wanted = {"standings": data["standings"], "trades": data["trades"], "matchups": data["matchups"]}

    kept, sec = [], None
    last_idx = {}   # section -> index in `kept` of its last non-blank row
    for r in rows:
        c0 = str(r[0] if r else "").strip()
        u0 = c0.upper()
        if u0.startswith("---"):
            if "PROFILE" in u0: sec = "profile"
            elif "STANDINGS" in u0: sec = "standings"
            elif "ROSTERS" in u0: sec = "rosters"
            elif "TRADE" in u0: sec = "trades"
            elif "BOX SCORES" in u0: sec = "boxscores"
            elif "MATCHUPS" in u0: sec = "matchups"
            else: sec = "other"
            kept.append(r)
            last_idx[sec] = len(kept) - 1
            continue
        if sec in wanted and c0 in seasons:
            continue                      # replaced by fresh data
        kept.append(r)
        if any(str(c).strip() for c in r):
            last_idx[sec] = len(kept) - 1

    missing = [k for k in wanted if k not in last_idx]
    if missing:
        print(f"!! target block has no {missing} section(s); those rows were not merged")

    for sec_name in sorted((k for k in wanted if k in last_idx), key=lambda k: -last_idx[k]):
        pos = last_idx[sec_name] + 1
        kept[pos:pos] = wanted[sec_name]
    return kept


def sync_fleaflicker():
    if not os.path.exists(MASTER_FILE):
        print(f"{MASTER_FILE} not found!")
        sys.exit(1)
    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        master = json.load(f)

    ok = False
    failures = []
    key_lookup = {k.strip().lower(): k for k in master}
    for league in LEAGUES_TO_SYNC:
        try:
            data = collect_league(league)
        except FleaError as e:
            print(f"!! {league['name']}: {e}")
            failures.append(league["name"])
            continue
        if not data:
            print(f"!! No data loaded for {league['name']} - leaving existing data untouched.")
            continue
        target = league.get("merge_into")
        if target:
            key = key_lookup.get(target.strip().lower())
            if not key:
                print(f"!! merge target '{target}' not found in {MASTER_FILE}; skipped")
                continue
            master[key] = merge_into_existing(master[key], data, league["start_season"], data["last"])
            print(f"Merged {league['name']} into '{key}'")
        else:
            master[league["name"]] = build_standalone_block(league, data)
        ok = True

    if ok:
        with open(MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(master, f, separators=(",", ":"))
    if failures:
        print(f"Fleaflicker sync INCOMPLETE - not updated: {failures}. Re-run the workflow in a few minutes.")
        sys.exit(1)
    if not ok:
        print("Fleaflicker sync FAILED: nothing was loaded.")
        sys.exit(1)
    print("Fleaflicker sync completed.")


if __name__ == "__main__":
    sync_fleaflicker()
