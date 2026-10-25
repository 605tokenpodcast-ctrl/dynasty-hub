"""
Fleaflicker -> sleeper_leagues_master.json sync.

Builds the same sections the Sleeper sync produces, so index.html treats the
Fleaflicker league like any other league:

  --- LEAGUE PROFILE ---
  --- PAST SEASONS STANDINGS & CHAMPIONS ---     (every season since START_SEASON)
  --- CURRENT ROSTERS & DRAFT PICKS ---
  --- TRADE HISTORY (ALL-TIME & ALL SEASONS) --- (every completed trade)
  --- ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS) --- (every game, every season)
  --- WEEKLY LINEUPS & OPTIMAL SCORES (ALL SEASONS) --- (current season, plus a few
      older seasons backfilled per run)
  --- WAIVER & FREE AGENT MOVES (ALL SEASONS) ---

Set FLEA_DEBUG=1 to also dump the first raw response of every endpoint into
./fleaflicker_debug/ (the workflow uploads that folder as a build artifact).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

# From leagues.json. A league with merge_into ran on Fleaflicker and then moved to Sleeper: its
# history is spliced into that existing block instead of getting its own.
LEAGUES_TO_SYNC = league_config.leagues("fleaflicker")

MASTER_FILE = "sleeper_leagues_master.json"
API_BASE = "https://www.fleaflicker.com/api/"
REQUEST_DELAY = 0.8           # seconds between calls - Fleaflicker answers HTTP 403 if you go faster
RETRY_BACKOFF = [5, 20, 60, 120]   # seconds to wait before each retry of a refused/failed call
SEASON_RETRY_COOLDOWN = 150   # extra cooldown before re-trying a season that failed outright
LAST_PLAYOFF_WEEK = 17        # every league's championship is week 17; week 18 is unused
FALLBACK_REG_SEASON_WEEKS = 14
FUTURE_PICK_SEASONS = 3       # how many upcoming draft classes to list per team
LINEUP_BACKFILL_PER_RUN = 2  # older seasons of lineups fetched per run (one boxscore call per game)
DEBUG = os.environ.get("FLEA_DEBUG") == "1"
FULL_REFRESH = os.environ.get("FLEA_FULL_REFRESH") == "1"  # re-fetch finished seasons too
DEBUG_DIR = "fleaflicker_debug"

# If the automatic champion / runner-up / 3rd-place detection ever gets a season
# wrong (e.g. two-week championship), pin it here by Fleaflicker team id:
#   PLACEMENT_OVERRIDES = {"2019": {"champion": 123456, "runner_up": 234567, "third": 345678}}
PLACEMENT_OVERRIDES = {}

BLANK = ["", "", "", "", "", "", ""]
LINEUPS_HEADER = "--- WEEKLY LINEUPS & OPTIMAL SCORES (ALL SEASONS) ---"
MOVES_HEADER = "--- WAIVER & FREE AGENT MOVES (ALL SEASONS) ---"
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


def fetch_scoreboard(league_id, season, keep_unplayed=False):
    """Returns {period: [game, ...]} with normalised games.

    keep_unplayed keeps scheduled games that haven't been played yet (written as 0-0),
    so the current season carries its full schedule like the Sleeper leagues do.
    """
    periods = {}
    seen_ids = set()
    max_period = LAST_PLAYOFF_WEEK
    for p in range(1, LAST_PLAYOFF_WEEK + 1):
        if p > max_period:
            break
        data = api("FetchLeagueScoreboard", league_id=league_id, season=season, scoring_period=p)
        if not data:
            break
        if p == 1:
            ordinals = [int(num(e.get("ordinal", e.get("value")), 0)) for e in (data.get("eligibleSchedulePeriods") or [])]
            ordinals = [o for o in ordinals if o > 0]
            if ordinals:
                max_period = min(max(ordinals), LAST_PLAYOFF_WEEK)
        games = []
        for g in data.get("games") or []:
            home, away = g.get("home") or {}, g.get("away") or {}
            if not home.get("id") or not away.get("id"):
                continue  # bye
            hs = num((g.get("homeScore") or {}).get("score", g.get("homeScore")))
            as_ = num((g.get("awayScore") or {}).get("score", g.get("awayScore")))
            final = bool(g.get("isFinalScore") or g.get("isFinal"))
            if not final and hs == 0 and as_ == 0 and not keep_unplayed:
                continue  # not played yet
            games.append({
                "gid": str(g.get("id") or f"{p}-{home.get('id')}-{away.get('id')}"),
                "home": home, "away": away,
                "hs": hs, "as": as_, "final": final,
                # Only present on playoff games; used to pin champion / 3rd place exactly
                "champ_game": bool(g.get("isChampionshipGame")),
                "third_game": bool(g.get("isThirdPlaceGame")),
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

    # Fleaflicker flags the championship / 3rd place games itself; trust that over the bracket heuristic
    flagged_champ = [g for p in playoff_periods for g in periods[p] if g.get("champ_game") and g["final"]]
    if flagged_champ:
        w, l = winner_loser(flagged_champ[-1])
        if w is not None:
            result = {"champion": w, "runner_up": l}
            flagged_third = [g for p in playoff_periods for g in periods[p] if g.get("third_game") and g["final"]]
            if flagged_third:
                w3, _ = winner_loser(flagged_third[-1])
                if w3 is not None:
                    result["third"] = w3
            return result

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
    periods = fetch_scoreboard(league_id, season, keep_unplayed=(season == current_season()))

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


# --------------------------------------------------------------------------- #
# draft results (which player each traded pick turned into)
# --------------------------------------------------------------------------- #
PICK_RE = re.compile(r"(\d{4} Round \d+\w* Pick(?: \(originally from (?:[^()]|\([^()]*\))*\))?)( -> Resulted in drafting: [^,\]]*)?")


def parse_draft_board(data, season):
    """
    (season, round, original owner id) -> "Player (POS)" from one FetchLeagueDraftBoard response.
    The board has one row per round and one cell per pick; `team` is whoever made the pick, so the
    original owner comes from the draft order. Cells may be listed by column or by pick order (and
    snake rounds run backwards), so use whichever reading agrees with the picks nobody traded.
    """
    order = [team_id_of(t) for t in (data or {}).get("draftOrder") or []]
    n = len(order)
    rows = (data or {}).get("rows") or []
    if not n or not rows:
        return {}

    def slot_of(c):
        return int(num((c.get("slot") or {}).get("slot"), 0))

    def by_column(i, c):
        return order[i] if i < n else None

    def by_slot(i, c):
        s_ = slot_of(c)
        return order[s_ - 1] if 1 <= s_ <= n else None

    def by_snake_slot(i, c):
        s_ = slot_of(c)
        return (order[n - s_] if c.get("descending") else order[s_ - 1]) if 1 <= s_ <= n else None

    def agreement(f):
        return sum(1 for r in rows for i, c in enumerate(r.get("cells") or [])
                   if c and not c.get("fromOtherTeam") and team_id_of(c.get("team"))
                   and f(i, c) == team_id_of(c.get("team")))

    orig_of = max((by_column, by_slot, by_snake_slot), key=agreement)
    out = {}
    for r in rows:
        for i, c in enumerate(r.get("cells") or []):
            if not c or not c.get("player"):
                continue
            pro = unwrap_player(c["player"])
            if not (pro.get("nameFull") or pro.get("nameLast")):
                continue
            rnd = int(num((c.get("slot") or {}).get("round") or r.get("round"), 0))
            orig = orig_of(i, c)
            if rnd and orig:
                out[(int(season), rnd, orig)] = player_label(pro)
    return out


def fetch_draft_results(league_id, trades, first, last):
    """Draft boards for every season whose picks were traded (finished drafts only)."""
    seasons = set()
    for t in trades:
        for side in t.get("teams") or []:
            for pk in side.get("picksObtained") or []:
                yr = pick_key_parts(pk)[0]
                if first <= yr <= last:
                    seasons.add(yr)
    out = {}
    for season in sorted(seasons):
        try:
            data = api("FetchLeagueDraftBoard", league_id=league_id, season=season)
            got = parse_draft_board(data, season)
        except FleaError as e:
            print(f"  draft {season} skipped: {e}")
            continue
        out.update(got)
        print(f"  draft {season}: {len(got)} picks made")
        if not got and season < current_season() and not out:
            # Unexpected response shape: log enough to fix the parser from the run log
            print(f"  (draft board keys: {sorted((data or {}).keys())[:12]})")
    return out


def copy_lineage(kept_rows, fresh_rows):
    """Stored trade rows (kept for their old team names) get the draft results from the
    freshly built copy of the same trade: same date and the same picks in the same order."""
    def picks(row):
        return [m.group(1).split(" (originally")[0] for m in PICK_RE.finditer(str(row[4]))]

    by_date = {}
    for f in fresh_rows:
        by_date.setdefault(f[1], []).append(f)
    out = []
    for k in kept_rows:
        match = next((f for f in by_date.get(k[1], []) if picks(f) == picks(k) and picks(k)), None)
        if not match:
            out.append(k)
            continue
        lineage = iter([m.group(2) or "" for m in PICK_RE.finditer(str(match[4]))])

        def fill(m):
            fresh = next(lineage, "")   # advance for every pick so they stay paired
            return m.group(0) if m.group(2) else m.group(1) + fresh
        text = PICK_RE.sub(fill, str(k[4]))
        out.append([*k[:4], text, *k[5:]])
    return out


def build_trade_rows(trades, season_labels, latest_label, drafted=None):
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
                player = (drafted or {}).get(pick_key_parts(pk))
                if player:
                    desc += f" -> Resulted in drafting: {player}"
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
    # This year's rookie picks stay listed until the NFL season starts (the rookie draft is over by
    # then); the season itself rolls over on March 1, months before the draft.
    first_year = season if date.today() < nfl_kickoff(season) else season + 1
    out = []
    for pk in (data or {}).get("picks") or []:
        yr, rnd, orig = pick_key_parts(pk)
        if not (rnd and first_year <= yr < first_year + FUTURE_PICK_SEASONS):
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
# lineups + waiver moves
# --------------------------------------------------------------------------- #
def optimal_points(slot_eligibility, pool):
    """Best starting score: slots (lists of allowed positions) filled from pool [(pos, pts)],
    most restrictive slot first."""
    remaining = sorted(pool, key=lambda x: -x[1])
    total = 0.0
    for allowed in sorted(slot_eligibility, key=len):
        for i, (pos, pts) in enumerate(remaining):
            if pos in allowed:
                total += pts
                remaining.pop(i)
                break
    return total


def fetch_lineup_rows(league_id, season, periods, labels):
    """One row per team per played week, same columns as the Sleeper sync."""
    rows = []
    for p in sorted(periods):
        for g in periods[p]:
            if not g["final"] and g["hs"] == 0 and g["as"] == 0:
                continue
            try:
                # No season here: Fleaflicker answers FetchLeagueBoxscore with HTTP 400 when it's given
                # one. The game id already pins the season; the week is dropped too if that call fails.
                box = (api("FetchLeagueBoxscore", league_id=league_id, scoring_period=p, fantasy_game_id=g["gid"])
                       or api("FetchLeagueBoxscore", league_id=league_id, fantasy_game_id=g["gid"]))
            except FleaError as e:
                print(f"  lineup {season} week {p}: {e}")
                continue
            if not box:
                continue
            sides = {"home": {"start": [], "bench": [], "slots": []}, "away": {"start": [], "bench": [], "slots": []}}
            for grp in box.get("lineups") or []:
                starting = str(grp.get("group") or "").upper() == "START"
                for slot in grp.get("slots") or []:
                    pos = slot.get("position") or {}
                    elig = pos.get("eligibility") or [pos.get("label")]
                    for side in ("home", "away"):
                        if starting:
                            sides[side]["slots"].append(set(elig))
                        lp = slot.get(side)
                        if not lp:
                            continue
                        pro = unwrap_player(lp)
                        pts = num(lp.get("viewingActualPoints"))
                        sides[side]["start" if starting else "bench"].append((pro.get("position") or "FLEX", pts, player_label(pro)))
            for side, score in (("home", g["hs"]), ("away", g["as"])):
                d = sides[side]
                if not d["start"] and not d["bench"]:
                    continue
                pool = [(pos, pts) for pos, pts, _ in d["start"] + d["bench"]]
                # Fleaflicker works out the best lineup itself (pointsHome / pointsAway); prefer it
                optimum = num((((box.get("points" + side.capitalize()) or {}).get("scoringPeriod") or {}).get("optimum")))
                best = max(optimum or optimal_points(d["slots"], pool), score)
                fmt = lambda xs: "; ".join(f"{label} {pts:.2f}" for _, pts, label in xs)
                rows.append([str(season), f"Week {p}", labels.get(g[side]["id"]) or team_label(g[side]),
                             f"{score:.2f}", f"{best:.2f}", fmt(d["start"]),
                             fmt(sorted(d["bench"], key=lambda x: -x[1]))])
    return rows


def fetch_move_rows(league_id, labels, season):
    """Waiver claims and free-agent adds for one season, newest first. Fleaflicker lists the drop
    that goes with an add as its own item, so a team's drops within a minute of an add are joined to it."""
    rows, drops, offset, seen = [], [], None, set()
    for _ in range(200):
        data = api("FetchLeagueTransactions", league_id=league_id, result_offset=offset)
        if not data:
            break
        older = False
        for item in data.get("items") or []:
            tx = item.get("transaction") or {}
            dt = epoch_to_dt(item.get("timeEpochMilli"))
            if not dt:
                continue
            tx_season, week = season_and_week(dt)
            if tx_season < season:
                older = True
                continue
            if tx_season != season:
                continue
            kind = str(tx.get("type") or "")
            team = tx.get("team") or {}
            if kind == "TRANSACTION_DROP":
                drops.append((dt, team.get("id"), player_label(unwrap_player(tx.get("player")))))
                continue
            if kind not in ("TRANSACTION_CLAIM", "TRANSACTION_ADD"):
                continue
            bid = tx.get("bidAmount") if tx.get("bidAmount") is not None else (tx.get("waiverBid") or "")
            rows.append([str(season), f"Week {week}", f"{dt.month}/{dt.day}/{dt.year}",
                         labels.get(team.get("id")) or team_label(team),
                         "Waiver" if kind == "TRANSACTION_CLAIM" else "Free Agent",
                         player_label(unwrap_player(tx.get("player"))), "", f"{num(bid, 0):g}" if bid != "" else "",
                         (dt, team.get("id"))])
        nxt = data.get("resultOffsetNext")
        if older or nxt is None or nxt in seen:
            break
        seen.add(nxt)
        offset = nxt
    return [attach_drops(r, drops) for r in rows]


def attach_drops(row, drops):
    """Fill the Dropped column of an add row (its last item is (time, team id)) from drops made
    by the same team within a minute of it."""
    (dt, team_id), out = row[8], row[:8]
    out[6] = ", ".join(label for t, tid, label in drops
                       if tid == team_id and abs((t - dt).total_seconds()) <= 60)
    return out


def existing_section_rows(rows, word):
    """Data rows of the section whose header contains `word` (upper case)."""
    out, active = [], False
    for r in rows or []:
        c0 = str(r[0] if r else "").strip()
        if c0.upper().startswith("---"):
            active = word in c0.upper()
            continue
        if active and c0 and c0 != "Season":
            out.append(r)
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def finished_seasons(rows, first, last):
    """{season: (standings rows, matchup rows)} for seasons in `rows` that already have a champion.
    A finished season never changes, so the sync reuses these rows instead of re-fetching them."""
    standings = existing_section_rows(rows, "STANDINGS")
    matchups = existing_section_rows(rows, "MATCHUPS")
    out = {}
    for season in range(first, last + 1):
        st = [r for r in standings if str(r[0]).strip() == str(season)]
        mu = [r for r in matchups if str(r[0]).strip() == str(season)]
        if st and mu and any("League Champion" in str(r[4]) for r in st):
            out[season] = (st, mu)
    return out


def trade_date(row):
    try:
        return datetime.strptime(str(row[1]), "%m/%d/%Y")
    except ValueError:
        return datetime(int(row[0]), 1, 1)


def collect_league(league, existing_rows=None, cache_rows=None):
    """Pull standings / matchups / trades (and rosters if it's a live season).
    Standalone leagues also get lineups and waiver moves; older seasons already in
    `existing_rows` are kept, and a few missing ones are backfilled each run.
    Finished seasons found in `cache_rows` (this league's current block) are reused, not re-fetched."""
    league_id, name = league["id"], league["name"]
    last = league.get("end_season") or current_season()
    cur = current_season()
    print(f"== {name} ({league_id}), seasons {league['start_season']}-{last}")

    standings_rows, matchup_rows = [], []
    season_labels, latest_label = {}, {}
    current_rows = []
    want_lineups = not league.get("merge_into")
    old_lineups = [r for r in existing_section_rows(existing_rows, "LINEUPS") if str(r[0]) != str(cur)]
    old_moves = [r for r in existing_section_rows(existing_rows, "FREE AGENT") if str(r[0]) != str(cur)]
    have_lineup_seasons = {str(r[0]) for r in old_lineups}
    backfill = sorted((y for y in range(league["start_season"], cur) if str(y) not in have_lineup_seasons),
                      reverse=True)[:LINEUP_BACKFILL_PER_RUN] if want_lineups else []
    lineup_rows = []
    cached = {} if FULL_REFRESH else finished_seasons(cache_rows, league["start_season"], min(last, cur - 1))
    if cached:
        print(f"  reusing {len(cached)} finished season(s) already in the file: {sorted(cached)}")

    def load_season(season):
        if season in cached and season not in backfill:
            standings_rows.extend(cached[season][0])
            matchup_rows.extend(cached[season][1])
            return
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
        if want_lineups and (season == cur or season in backfill):
            new_rows = fetch_lineup_rows(league_id, season, periods, season_labels[season])
            lineup_rows.extend(new_rows)
            print(f"  {len(new_rows)} lineup rows")
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
    drafted = fetch_draft_results(league_id, trades, league["start_season"], min(last, cur))
    trade_rows = build_trade_rows(trades, season_labels, latest_label, drafted)
    # a league that has an end_season must not pick up trades from later seasons
    trade_rows = [t for t in trade_rows if int(t[0]) <= last]
    # Reused seasons keep their stored trade rows, which were labelled with that season's team names
    reused = {s for s in cached if s not in backfill}
    if reused:
        kept = copy_lineage([t for t in existing_section_rows(cache_rows, "TRADE") if int(t[0]) in reused],
                            trade_rows)
        trade_rows = sorted([t for t in trade_rows if int(t[0]) not in reused] + kept, key=trade_date, reverse=True)
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
    move_rows = []
    if want_lineups and current_rows:
        print("- waiver & free agent moves")
        try:
            move_rows = fetch_move_rows(league_id, latest_label, cur)
        except FleaError as e:
            print(f"  moves skipped: {e}")
        print(f"  {len(move_rows)} moves")
    lineup_rows.sort(key=lambda r: (-int(r[0]), int(r[1].split()[-1])))
    old_lineups = [r for r in old_lineups if str(r[0]) not in {x[0] for x in lineup_rows}]
    return {"standings": standings_rows, "matchups": matchup_rows, "trades": trade_rows,
            "rosters": roster_rows, "last": last,
            "lineups": lineup_rows + old_lineups, "moves": move_rows + old_moves}


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
    ] + data["matchups"] + [
        BLANK,
        [LINEUPS_HEADER, "", "", "", "", "", ""],
        ["Season", "Week", "Team / Manager", "Score", "Optimal Score", "Starters (Name (Pos) Pts)", "Bench (Name (Pos) Pts)"],
    ] + data["lineups"] + [
        BLANK,
        [MOVES_HEADER, "", "", "", "", "", "", ""],
        ["Season", "Week", "Date", "Team / Manager", "Type", "Added", "Dropped", "FAAB Bid"],
    ] + data["moves"]


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
            own_rows = master.get(key_lookup.get(league["name"].strip().lower(), league["name"]))
            target_key = key_lookup.get((league.get("merge_into") or "").strip().lower())
            data = collect_league(league, own_rows, master.get(target_key) if league.get("merge_into") else own_rows)
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
