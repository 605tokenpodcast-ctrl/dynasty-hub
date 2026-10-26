"""Unit tests for the sync scripts' pure logic. Run with: python -m unittest discover tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import sync_fleaflicker  # noqa: E402
import sync_leagues  # noqa: E402
import sync_trade_values  # noqa: E402

SEC = lambda title: [f"--- {title} ---", "", "", "", "", "", ""]  # noqa: E731


class TradeDedupe(unittest.TestCase):
    def test_legacy_copy_dropped_and_lineage_kept(self):
        with_id = ["2025", "9/1/2025", "Week 1", "A & B", "A received: [X (WR), Y (RB)] <---> B received: [Z (QB)]", "tx1", ""]
        legacy = ["2025", "9/2/2025", "Week 1", "A & B",
                  "A received: [Y (RB), X (WR)] <---> B received: [Z (QB) -> Resulted in drafting: Rookie]", "", ""]
        kept, removed = sync_leagues.drop_duplicate_trades([with_id, legacy])
        self.assertEqual(removed, 1)
        self.assertEqual(kept, [with_id])
        self.assertIn("Resulted in drafting: Rookie", kept[0][4])

    def test_different_trades_kept(self):
        a = ["2025", "9/1/2025", "Week 1", "A & B", "A received: [X (WR)] <---> B received: [Z (QB)]", "tx1", ""]
        b = ["2025", "9/1/2025", "Week 1", "A & B", "A received: [Q (WR)] <---> B received: [Z (QB)]", "", ""]
        self.assertEqual(sync_leagues.drop_duplicate_trades([a, b]), ([a, b], 0))


class CountRows(unittest.TestCase):
    def test_counts_only_season_in_section(self):
        rows = [SEC("TRADE HISTORY"), ["Season"], ["2026", "", "", "", "", "tx", ""], ["2026", "", "", "", "", "", ""],
                ["2025", "", "", "", "", "tx2", ""], SEC("ALL-TIME MATCHUPS"), ["2026"]]
        self.assertEqual(sync_leagues.count_rows(rows, "TRADE", "2026"), 2)
        self.assertEqual(sync_leagues.count_rows(rows, "TRADE", "2026", with_tx_id=True), 1)
        self.assertEqual(sync_leagues.count_rows(rows, "MATCHUPS", "2026"), 1)

    def test_played_only_skips_zero_point_lineups(self):
        rows = [SEC("WEEKLY LINEUPS"), ["Season"], ["2026", "Week 1", "A", "101.50", "120.00", "", ""],
                ["2026", "Week 9", "A", "0.00", "0.00", "", ""]]
        self.assertEqual(sync_leagues.count_rows(rows, "LINEUPS", "2026"), 2)
        self.assertEqual(sync_leagues.count_rows(rows, "LINEUPS", "2026", played_only=True), 1)


class Placements(unittest.TestCase):
    labels = {1: "Alpha Dogs (alpha)", 2: "beta", 3: "Gamma (gamma)", 4: "Delta (delta)"}

    def bracket(self, games):
        with mock.patch.object(sync_leagues, 'fetch_json', return_value=games):
            return sync_leagues.bracket_placements("L", self.labels)

    def test_final_and_third_place(self):
        out = self.bracket([{"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
                            {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 2, "l": 1, "p": 1},
                            {"r": 2, "m": 4, "t1": 3, "t2": 4, "w": 3, "l": 4, "p": 3}])
        self.assertEqual(out, {"beta": "🏆 League Champion", "alpha": "🥈 Runner-Up", "gamma": "🥉 3rd Place"})

    def test_no_third_place_when_league_plays_none(self):
        games = [{"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 2, "l": 1, "p": 1},
                 {"r": 2, "m": 4, "t1": 3, "t2": 4, "w": 3, "l": 4, "p": 3}]
        with mock.patch.object(sync_leagues, 'fetch_json', return_value=games):
            out = sync_leagues.bracket_placements("L", self.labels, third_place_game=False)
        self.assertEqual(out, {"beta": "🏆 League Champion", "alpha": "🥈 Runner-Up"})

    def test_nothing_until_final_is_decided(self):
        self.assertEqual(self.bracket([{"r": 2, "m": 3, "t1": 1, "t2": 2, "w": None, "l": None, "p": 1}]), {})
        self.assertEqual(self.bracket([]), {})

    def test_apply_matches_renamed_team_by_display_name(self):
        rows = [["2026", "New Team Name (alpha)", "9-5", "1700.00", "Regular Season", "", ""],
                ["2026", "beta", "5-9", "1600.00", "Regular Season", "", ""],
                ["2026", "Other (omega)", "4-10", "1500.00", "Regular Season", "", ""]]
        n = sync_leagues.apply_placements(rows, {"alpha": "🥈 Runner-Up", "beta": "🏆 League Champion"})
        self.assertEqual(n, 2)
        self.assertEqual([r[4] for r in rows], ["🥈 Runner-Up", "🏆 League Champion", "Regular Season"])


class Renewal(unittest.TestCase):
    def fake(self, responses):
        return lambda url, retries=4: responses.get(url.rsplit('/v1/', 1)[1])

    def test_finds_next_season_league(self):
        responses = {"league/OLD/users": [{"user_id": "u1"}, {"user_id": "u2"}],
                     "user/u1/leagues/nfl/2027": [{"league_id": "X", "previous_league_id": "OTHER"}],
                     "user/u2/leagues/nfl/2027": [{"league_id": "NEW", "previous_league_id": "OLD"}]}
        with mock.patch.object(sync_leagues, 'fetch_json', side_effect=self.fake(responses)):
            found = sync_leagues.find_renewed_league({"league_id": "OLD", "season": "2026"}, {"league_season": "2027"})
        self.assertEqual(found["league_id"], "NEW")

    def test_no_lookup_while_season_is_current(self):
        with mock.patch.object(sync_leagues, 'fetch_json', side_effect=AssertionError("no calls expected")):
            self.assertIsNone(sync_leagues.find_renewed_league({"league_id": "OLD", "season": "2026"}, {"league_season": "2026"}))
            self.assertIsNone(sync_leagues.find_renewed_league({"league_id": "OLD", "season": "2026"}, None))


class Profile(unittest.TestCase):
    def test_set_profile_updates_or_appends(self):
        rows = [["League ID", "1", "", "", "", "", ""]]
        sync_leagues.set_profile(rows, "League ID", "2")
        sync_leagues.set_profile(rows, "Current Season", "2027")
        self.assertEqual([r[:2] for r in rows], [["League ID", "2"], ["Current Season", "2027"]])


class OpenWeek(unittest.TestCase):
    def test_current_week_only_during_that_regular_season(self):
        self.assertEqual(sync_leagues.open_week({"season": "2026", "season_type": "regular", "week": 8}, "2026"), "8")
        self.assertEqual(sync_leagues.open_week({"season": "2026", "season_type": "regular", "week": 8}, "2025"), "")
        self.assertEqual(sync_leagues.open_week({"season": "2026", "season_type": "off", "week": 0}, "2026"), "")
        self.assertEqual(sync_leagues.open_week({"season": "2026", "season_type": "regular", "week": 18}, "2026"), "")
        self.assertEqual(sync_leagues.open_week(None, "2026"), "")


class PlayerMeta(unittest.TestCase):
    def test_injuries_and_defenses(self):
        players = {"1": {"full_name": "A Guy", "position": "RB", "active": True, "injury_status": "Q", "age": 24},
                   "2": {"full_name": "B Guy", "position": "WR", "active": True},
                   "KC": {"first_name": "Kansas City", "last_name": "Chiefs", "position": "DEF"}}
        meta, ids, injuries = sync_leagues.build_player_meta(players)
        self.assertEqual(ids, {"1": "A Guy (RB)", "2": "B Guy (WR)", "KC": "Kansas City Chiefs (DEF)"})
        self.assertEqual(injuries, {"1": "Q"})
        self.assertEqual(meta["A Guy"][0], 24)


class FleaflickerMoves(unittest.TestCase):
    def test_drop_joined_to_same_team_add_within_a_minute(self):
        from datetime import datetime, timezone
        t = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        row = ["2026", "Week 5", "10/7/2026", "Team", "Waiver", "New Guy (WR)", "", "5", (t, 7)]
        drops = [(t, 7, "Old Guy (RB)"), (t, 8, "Other Team Guy (TE)"),
                 (datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc), 7, "Later Drop (K)")]
        self.assertEqual(sync_fleaflicker.attach_drops(row, drops),
                         ["2026", "Week 5", "10/7/2026", "Team", "Waiver", "New Guy (WR)", "Old Guy (RB)", "5"])


class FleaflickerDraftLineage(unittest.TestCase):
    BOARD = {
        "draftOrder": [{"id": 1}, {"id": 2}, {"id": 3}],
        "rows": [
            {"round": 1, "cells": [
                {"team": {"id": 1}, "slot": {"round": 1, "slot": 1}, "player": {"proPlayer": {"nameFull": "A One", "position": "RB"}}},
                {"team": {"id": 1}, "fromOtherTeam": True, "slot": {"round": 1, "slot": 2}, "player": {"proPlayer": {"nameFull": "B Two", "position": "WR"}}},
                {"team": {"id": 3}, "slot": {"round": 1, "slot": 3}, "player": {"proPlayer": {"nameFull": "C Three", "position": "QB"}}},
            ]},
            # snake round listed in pick order: team 3 picks first
            {"round": 2, "cells": [
                {"team": {"id": 3}, "descending": True, "slot": {"round": 2, "slot": 1}, "player": {"proPlayer": {"nameFull": "D Four", "position": "TE"}}},
                {"team": {"id": 2}, "descending": True, "slot": {"round": 2, "slot": 2}, "player": {"proPlayer": {"nameFull": "E Five", "position": "WR"}}},
                {"team": {"id": 1}, "descending": True, "slot": {"round": 2, "slot": 3}},
            ]},
        ],
    }

    def test_board_keys_picks_by_original_owner(self):
        got = sync_fleaflicker.parse_draft_board(self.BOARD, 2024)
        self.assertEqual(got[(2024, 1, "2")], "B Two (WR)")   # team 1 used team 2's pick
        self.assertEqual(got[(2024, 2, "3")], "D Four (TE)")
        self.assertNotIn((2024, 2, "1"), got)                  # not picked yet

    def test_ordered_selections_without_draft_order(self):
        def pick(rnd, slot, team, name, traded=False):
            c = {"slot": {"round": rnd, "slot": slot, "overall": (rnd - 1) * 3 + slot}, "team": {"id": team},
                 "player": {"proPlayer": {"nameFull": name, "position": "RB"}}}
            if traded:
                c["fromOtherTeam"] = True
            return c
        # linear draft, slots owned by 7, 8, 9; team 9 used team 7's 3rd-round pick
        data = {"draftIndex": 9, "orderedSelections": [
            pick(1, 1, 7, "A"), pick(1, 2, 8, "B"), pick(1, 3, 9, "C"),
            pick(2, 1, 7, "D"), pick(2, 2, 8, "E"), pick(2, 3, 9, "F"),
            pick(3, 1, 9, "G", traded=True), pick(3, 2, 8, "H"), pick(3, 3, 9, "I"),
        ]}
        got = sync_fleaflicker.parse_draft_board(data, 2019)
        self.assertEqual(got[(2019, 3, "7")], "G (RB)")
        self.assertEqual(got[(2019, 3, "9")], "I (RB)")
        self.assertEqual(len(got), 9)

    def test_own_pick_without_original_owner(self):
        # team 2 sends its own 1st (no originalOwner on it) to team 1
        trade = {"approvedOn": 1700000000000, "teams": [
            {"team": {"id": 1, "name": "One"}, "picksObtained": [{"season": 2024, "slot": {"round": 1}}]},
            {"team": {"id": 2, "name": "Two"}, "playersObtained": [{"proPlayer": {"nameFull": "Vet", "position": "QB"}}]},
        ]}
        drafted = sync_fleaflicker.parse_draft_board(self.BOARD, 2024)
        rows = sync_fleaflicker.build_trade_rows([trade], {}, {}, drafted)
        self.assertIn("2024 Round 1st Pick -> Resulted in drafting: B Two (WR)", rows[0][4])

    def test_team_that_traded_a_whole_round(self):
        # no draftOrder; team 7 traded both its picks, so its slot can't be read off the board
        def pick(rnd, slot, team, name, traded=False):
            return {"slot": {"round": rnd, "slot": slot}, "team": {"id": team}, "fromOtherTeam": traded,
                    "player": {"proPlayer": {"nameFull": name, "position": "WR"}}}
        data = {"orderedSelections": [
            pick(1, 1, 9, "A", True), pick(1, 2, 8, "B"), pick(1, 3, 9, "C"),
            pick(2, 1, 8, "D", True), pick(2, 2, 8, "E"), pick(2, 3, 9, "F"),
        ]}
        traded = {(2019, 1, "7"): "9", (2019, 2, "7"): "8"}
        got = sync_fleaflicker.parse_draft_board(data, 2019, traded)
        self.assertEqual(got[(2019, 1, "7")], "A (WR)")
        self.assertEqual(got[(2019, 2, "7")], "D (WR)")
        self.assertEqual(got[(2019, 1, "9")], "C (WR)")

    def test_passed_on_pick_keeps_its_original_owner(self):
        # Older Fleaflicker trades carry no originalOwner. A team sends its own pick while it has it,
        # then the one it picked up; with several picked up (and its own gone) the pick stays unknown.
        moves = [(2, 1), (1, 3), (1, 4), (3, 5), (3, 6), (5, 6), (6, 11), (6, 12)]   # (from, to), in time order
        trades = [{"approvedOn": n, "teams": [
            {"team": {"id": to}, "picksObtained": [{"season": 2024, "slot": {"round": 1}}]},
            {"team": {"id": frm}}]} for n, (frm, to) in enumerate(moves, 1)]
        sync_fleaflicker.resolve_pick_origins(list(reversed(trades)))   # input order doesn't matter
        origins = [sync_fleaflicker.traded_pick_key(t["teams"][0]["picksObtained"][0], t["teams"][0], t["teams"])[2]
                   for t in trades]
        self.assertEqual(origins, ["2", "1", "2", "3", "1", "5", "6", None])

    def test_draft_board_picker_decides_which_pick_was_sent(self):
        # Team 1 picks up team 2's 1st, then sends "a 1st" to team 3. Without the board that's its own;
        # the board shows team 3 made the pick in team 2's slot, so it was team 2's.
        trades = [{"approvedOn": n, "teams": [{"team": {"id": to}, "picksObtained": [{"season": 2024, "slot": {"round": 1}}]},
                                              {"team": {"id": frm}}]} for n, (frm, to) in enumerate([(2, 1), (1, 3)], 1)]
        key = lambda t: sync_fleaflicker.traded_pick_key(t["teams"][0]["picksObtained"][0], t["teams"][0], t["teams"])  # noqa: E731
        sync_fleaflicker.resolve_pick_origins(trades)
        self.assertEqual(key(trades[1]), (2024, 1, "1"))
        sync_fleaflicker.resolve_pick_origins(trades, {(2024, 1, "2"): "3", (2024, 1, "1"): "1"})
        self.assertEqual(key(trades[1]), (2024, 1, "2"))

    def test_fresh_lineage_replaces_stored(self):
        fresh = [["2020", "7/7/2020", "Week 1", "A & B", "A received: [2021 Round 2nd Pick -> Resulted in drafting: Right (QB)] <---> B received: [X (WR)]", "", ""]]
        old = ["2020", "7/7/2020", "Week 1", "A & B", "Old A received: [2021 Round 2nd Pick -> Resulted in drafting: Wrong (QB)] <---> Old B received: [X (WR)]", "", ""]
        self.assertIn("Right (QB)", sync_fleaflicker.copy_lineage([old], fresh)[0][4])
        none = [[*fresh[0][:4], "A received: [2021 Round 2nd Pick] <---> B received: [X (WR)]", "", ""]]
        self.assertNotIn("Resulted", sync_fleaflicker.copy_lineage([old], none)[0][4])
        self.assertIn("Wrong (QB)", sync_fleaflicker.copy_lineage([old], none, {2021})[0][4])   # draft unreadable this run

    def test_empty_board(self):
        self.assertEqual(sync_fleaflicker.parse_draft_board({}, 2017), {})

    def test_trade_rows_and_kept_rows_get_lineage(self):
        trade = {"approvedOn": 1700000000000, "teams": [
            {"team": {"id": 1, "name": "One"}, "picksObtained": [{"season": 2024, "slot": {"round": 1}, "originalOwner": {"id": 2}}]},
            {"team": {"id": 2, "name": "Two"}, "playersObtained": [{"proPlayer": {"nameFull": "Vet", "position": "QB"}}]},
        ]}
        drafted = sync_fleaflicker.parse_draft_board(self.BOARD, 2024)
        fresh = sync_fleaflicker.build_trade_rows([trade], {}, {}, drafted)
        self.assertIn("2024 Round 1st Pick (originally from Team 2) -> Resulted in drafting: B Two (WR)", fresh[0][4])
        old = [*fresh[0][:3], "Old & Names", "Old One received: [2024 Round 1st Pick (originally from Old Two)] <---> Old Two received: [Vet (QB)]", "", ""]
        kept = sync_fleaflicker.copy_lineage([old], fresh)
        self.assertEqual(kept[0][4], "Old One received: [2024 Round 1st Pick (originally from Old Two) -> Resulted in drafting: B Two (WR)] <---> Old Two received: [Vet (QB)]")


class FleaflickerFinishedSeasons(unittest.TestCase):
    def test_only_seasons_with_a_champion_are_reused(self):
        rows = [SEC("PAST SEASONS STANDINGS & CHAMPIONS"), ["Season"],
                ["2025", "A", "9-5", "1", "🏆 League Champion", "", ""], ["2025", "B", "5-9", "1", "Regular Season", "", ""],
                ["2024", "A", "9-5", "1", "Regular Season", "", ""],
                SEC("ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS)"), ["Season"],
                ["2025", "Week 1", "1", "A", "100", "B", "90"], ["2024", "Week 1", "1", "A", "100", "B", "90"]]
        out = sync_fleaflicker.finished_seasons(rows, 2023, 2025)
        self.assertEqual(sorted(out), [2025])
        self.assertEqual(len(out[2025][0]), 2)
        self.assertEqual(len(out[2025][1]), 1)
        self.assertEqual(sync_fleaflicker.finished_seasons(None, 2023, 2025), {})


class PastSleeperTrades(unittest.TestCase):
    def row(self, date, breakdown, tx=""):
        return ["2022", date, "Week 3", "A & B", breakdown, tx, ""]

    def test_legacy_row_gets_id_instead_of_a_copy(self):
        legacy = self.row("9/20/2022", "Old A received: [X (WR), 2023 Round 1st Pick (originally from Old B)] <---> Old B received: [Y (RB)]")
        trades = [legacy]
        found = [self.row("9/21/2022", "A received: [2023 Round 1st Pick (originally from B), X (WR)] <---> B received: [Y (RB)]", "t1"),
                 self.row("10/1/2022", "A received: [Z (QB)] <---> B received: [Nothing]", "t2")]
        self.assertEqual(sync_leagues.merge_past_trades(trades, found), 1)
        self.assertEqual(len(trades), 2)
        self.assertEqual(legacy[5], "t1")
        self.assertIn("Old A", legacy[4])      # stored text (old team names) kept
        self.assertEqual(trades[1][5], "t2")
        self.assertEqual(sync_leagues.merge_past_trades(trades, found), 0)   # nothing added twice

    def test_mostly_same_items_match_far_dates_do_not(self):
        legacy = self.row("9/20/2022", "A received: [Kenneth Walker (RB), X (WR)] <---> B received: [Y (RB)]")
        far = self.row("12/20/2022", "A received: [X (WR)] <---> B received: [Y (RB)]")
        trades = [legacy, far]
        found = [self.row("9/20/2022", "A received: [Kenneth Walker III (RB), X (WR)] <---> B received: [Y (RB)]", "t1")]
        self.assertEqual(sync_leagues.merge_past_trades(trades, found), 0)
        self.assertEqual((legacy[5], far[5]), ("t1", ""))


class SleeperDraftLineage(unittest.TestCase):
    def test_traded_pick_gets_player_from_original_slot(self):
        api = {
            "https://api.sleeper.app/v1/league/L26/users": [{"user_id": "u1", "display_name": "alpha"}, {"user_id": "u2", "display_name": "beta"}],
            "https://api.sleeper.app/v1/league/L26/drafts": [{"draft_id": "d1", "season": "2026", "status": "complete", "draft_order": {"u2": 1, "u1": 2}}],
            # beta (slot 1) traded its 1st to alpha, who made both picks
            "https://api.sleeper.app/v1/draft/d1/picks": [{"round": 1, "draft_slot": 1, "roster_id": 1, "player_id": "p1"},
                                                          {"round": 1, "draft_slot": 2, "roster_id": 1, "player_id": "p2"}],
        }
        players = {"p1": {"full_name": "Rookie One", "position": "WR"}, "p2": {"full_name": "Rookie Two", "position": "RB"}}
        with mock.patch.object(sync_leagues, 'fetch_json', side_effect=lambda url: api.get(url)):
            drafted, done = sync_leagues.draft_results({"league_id": "L26", "season": "2026", "previous_league_id": None}, {"2026"}, players)
        self.assertEqual(done, {"2026"})
        trades = [["2025", "9/1/2025", "Week 1", "A & B",
                   "Team A (alpha) received: [2026 Round 1st Pick (originally from Old Name (beta))] <---> Team B (beta) received: [Vet (QB), "
                   "2027 Round 2nd Pick (originally from Team A (alpha))]", "t1", ""]]
        self.assertEqual(sync_leagues.open_pick_years(trades, "2026"), {"2026"})
        self.assertEqual(sync_leagues.add_draft_lineage(trades, drafted), 1)
        self.assertIn("2026 Round 1st Pick (originally from Old Name (beta)) -> Resulted in drafting: Rookie One (WR)]", trades[0][4])
        self.assertEqual(sync_leagues.open_pick_years(trades, "2026"), set())
        self.assertEqual(sync_leagues.add_draft_lineage(trades, drafted), 0)   # never added twice


class FleaflickerPicksUsedOnSleeper(unittest.TestCase):
    def test_pick_traded_on_fleaflicker_gets_sleeper_draft_result(self):
        target = next(lg for lg in sync_fleaflicker.league_config.leagues("sleeper") if lg["name"] == "Hail Mary Jane Congregation")
        S = "https://api.sleeper.app/v1"
        api = {
            f"{S}/league/{target['id']}": {"league_id": target["id"], "season": "2022", "previous_league_id": "L21"},
            f"{S}/league/{target['id']}/users": [{"user_id": "u1", "display_name": "jarvisevans"}, {"user_id": "u2", "display_name": "Kronik"}],
            f"{S}/league/{target['id']}/drafts": [{"draft_id": "d22", "season": "2022", "status": "complete",
                                                  "settings": {"rounds": 5}, "draft_order": {"u1": 1, "u2": 2}}],
            f"{S}/draft/d22/picks": [{"round": 1, "draft_slot": 1, "player_id": "p1", "metadata": {"first_name": "Rook", "last_name": "Ie", "position": "WR"}},
                                     {"round": 1, "draft_slot": 2, "player_id": "p2", "metadata": {"first_name": "Other", "last_name": "Guy", "position": "RB"}}],
        }
        # Jarvis1983 (Fleaflicker team 7) sent its own 2022 1st to team 8 in 2020
        trades = [{"approvedOn": 1, "teams": [{"team": {"id": 8, "name": "Eight"}, "picksObtained": [{"season": 2022, "slot": {"round": 1}}]},
                                              {"team": {"id": 7, "name": "Beats by J"}}]}]
        sync_fleaflicker.resolve_pick_origins(trades)
        standings = {"teams": [{"id": 7, "name": "Beats by J", "owners": [{"displayName": "Jarvis1983"}]},
                               {"id": 8, "name": "Eight", "owners": [{"displayName": "andylang1031"}]}]}
        sync_leagues._LEAGUES.clear()
        with mock.patch.object(sync_leagues, 'fetch_json', side_effect=lambda url: api.get(url)), \
                mock.patch.object(sync_fleaflicker, 'api', return_value=standings):
            out, failed = sync_fleaflicker.sleeper_draft_results({"id": "181202", "merge_into": "Hail Mary Jane Congregation"}, trades, 2020)
        sync_leagues._LEAGUES.clear()
        self.assertEqual(out, {(2022, 1, "7"): "Rook Ie (WR)"})
        self.assertEqual(failed, set())


class FleaflickerProfileMarkers(unittest.TestCase):
    def test_set_and_read_checked_seasons(self):
        rows = [SEC("LEAGUE PROFILE"), ["League ID", "1", "", "", "", "", ""], ["", "", "", "", "", "", ""],
                SEC("PAST SEASONS STANDINGS & CHAMPIONS")]
        sync_fleaflicker.set_checked(rows, "Fleaflicker Moves Checked", {2017, 2016})
        self.assertEqual(rows[2][:2], ["Fleaflicker Moves Checked", "2016, 2017"])
        sync_fleaflicker.set_checked(rows, "Fleaflicker Moves Checked", {2018})
        self.assertEqual(sync_fleaflicker.checked_seasons(rows, "Fleaflicker Moves Checked"), {2016, 2017, 2018})
        self.assertEqual(len(rows), 5)


def fake_fleaflicker(endpoint, **p):
    """A two-team Fleaflicker league that ran 2019-2020: one game a week, weeks 1-2."""
    season = p.get("season")
    team = lambda i: {"id": i, "name": f"T{i}", "owners": [{"displayName": f"o{i}"}]}  # noqa: E731
    if endpoint == "FetchLeagueStandings":
        return {"divisions": [{"teams": [dict(team(1), recordOverall={"wins": 2, "losses": 0}, pointsFor=200),
                                         dict(team(2), recordOverall={"wins": 0, "losses": 2}, pointsFor=150)]}]}
    if endpoint == "FetchLeagueScoreboard":
        if p["scoring_period"] > 2:
            return {"games": []}
        return {"eligibleSchedulePeriods": [{"ordinal": 1}, {"ordinal": 2}], "games": [{
            "id": f"{season}{p['scoring_period']}", "home": team(1), "away": team(2), "isFinalScore": True,
            "isChampionshipGame": p["scoring_period"] == 2, "homeScore": {"score": {"value": 100}}, "awayScore": {"score": {"value": 75}}}]}
    if endpoint == "FetchLeagueBoxscore":
        slot = lambda pos, a, b: {"position": {"label": pos, "eligibility": [pos]},  # noqa: E731
                                  "home": {"proPlayer": {"nameFull": a, "position": pos}, "viewingActualPoints": {"value": 100}},
                                  "away": {"proPlayer": {"nameFull": b, "position": pos}, "viewingActualPoints": {"value": 75}}}
        return {"lineups": [{"group": "START", "slots": [slot("QB", "Home QB", "Away QB")]}]}
    if endpoint == "FetchLeagueTransactions":
        ms = lambda y, m, d: int(__import__("datetime").datetime(y, m, d, 12).timestamp() * 1000)  # noqa: E731
        return {"items": [
            {"timeEpochMilli": ms(2021, 9, 20), "transaction": {"type": "TRANSACTION_ADD", "team": team(1), "player": {"proPlayer": {"nameFull": "Too New", "position": "WR"}}}},
            {"timeEpochMilli": ms(2020, 10, 1), "transaction": {"type": "TRANSACTION_CLAIM", "team": team(2), "bidAmount": 4, "player": {"proPlayer": {"nameFull": "Waiver Guy", "position": "RB"}}}},
            {"timeEpochMilli": ms(2019, 10, 1), "transaction": {"type": "TRANSACTION_ADD", "team": team(1), "player": {"proPlayer": {"nameFull": "Old Add", "position": "TE"}}}},
            {"timeEpochMilli": ms(2018, 10, 1), "transaction": {"type": "TRANSACTION_ADD", "team": team(1), "player": {"proPlayer": {"nameFull": "Before", "position": "K"}}}},
        ]}
    if endpoint == "FetchTrades":
        return {"trades": []}
    return None


class FleaflickerMergedLeagueHistory(unittest.TestCase):
    """A league's Fleaflicker years (merge_into) get lineups and waiver moves in the Sleeper block."""
    LEAGUE = {"name": "Old (Fleaflicker era)", "platform": "fleaflicker", "id": "9", "type": "dynasty",
              "start_season": 2019, "end_season": 2020, "merge_into": "Main"}

    def sleeper_block(self):
        return [SEC("LEAGUE PROFILE"), ["League ID", "S1", "", "", "", "", ""], ["", "", "", "", "", "", ""],
                SEC("PAST SEASONS STANDINGS & CHAMPIONS"), ["Season"], ["2021", "T1 (o1)", "9-5", "1", "Regular Season", "", ""],
                ["", "", "", "", "", "", ""], SEC("TRADE HISTORY (ALL-TIME & ALL SEASONS)"), ["Season"],
                ["", "", "", "", "", "", ""], SEC("ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS)"), ["Season"],
                ["2021", "Week 1", "1", "T1 (o1)", "1", "T2 (o2)", "2"], ["", "", "", "", "", "", ""],
                [sync_fleaflicker.LINEUPS_HEADER, "", "", "", "", "", ""], ["Season"],
                ["2021", "Week 1", "T1 (o1)", "1", "1", "", ""], ["", "", "", "", "", "", ""],
                [sync_fleaflicker.MOVES_HEADER, "", "", "", "", "", "", ""], ["Season"],
                ["2021", "Week 2", "9/20/2021", "T1 (o1)", "Free Agent", "Sleeper Add (WR)", "", ""]]

    def run_sync(self, block):
        with mock.patch.object(sync_fleaflicker, "api", side_effect=fake_fleaflicker), \
                mock.patch.object(sync_fleaflicker, "current_season", return_value=2026):
            data = sync_fleaflicker.collect_league(self.LEAGUE, None, block)
        return sync_fleaflicker.merge_into_existing(block, data, 2019, data["last"])

    def test_lineups_and_moves_spliced_into_sleeper_block(self):
        merged = self.run_sync(self.sleeper_block())
        lineups = sync_fleaflicker.existing_section_rows(merged, "LINEUPS")
        self.assertEqual(sorted({r[0] for r in lineups}), ["2019", "2020", "2021"])
        self.assertEqual(len([r for r in lineups if r[0] == "2020"]), 4)   # 2 teams x 2 weeks
        self.assertIn("Home QB (QB) 100.00", next(r for r in lineups if r[0] == "2020")[5])
        moves = sync_fleaflicker.existing_section_rows(merged, "FREE AGENT")
        self.assertEqual([(r[0], r[5]) for r in moves],
                         [("2021", "Sleeper Add (WR)"), ("2020", "Waiver Guy (RB)"), ("2019", "Old Add (TE)")])
        self.assertEqual(sync_fleaflicker.checked_seasons(merged, sync_fleaflicker.MOVES_CHECKED), {2019, 2020})

        # A second run reuses what is stored: no duplicate rows, no more box score calls
        with mock.patch.object(sync_fleaflicker, "fetch_lineup_rows", side_effect=AssertionError("refetched")):
            again = self.run_sync(merged)
        for word in ("LINEUPS", "FREE AGENT", "MATCHUPS", "STANDINGS"):
            self.assertEqual(sync_fleaflicker.existing_section_rows(again, word),
                             sync_fleaflicker.existing_section_rows(merged, word), word)

    def test_season_with_a_missing_box_score_is_retried(self):
        def flaky(endpoint, **p):
            if endpoint == "FetchLeagueBoxscore" and str(p.get("fantasy_game_id")) == "20192":
                return None
            return fake_fleaflicker(endpoint, **p)
        with mock.patch.object(sync_fleaflicker, "api", side_effect=flaky), \
                mock.patch.object(sync_fleaflicker, "current_season", return_value=2026):
            data = sync_fleaflicker.collect_league(self.LEAGUE, None, self.sleeper_block())
        self.assertEqual(sorted({r[0] for r in data["lineups"]}), ["2020"])
        self.assertEqual(data["checked"][sync_fleaflicker.LINEUPS_CHECKED], {2020})


if __name__ == '__main__':
    unittest.main()


class TradeValuesAtGrade(unittest.TestCase):
    PLAYERS = '"player","pos","ecr_1qb","ecr_2qb","value_1qb","value_2qb"\n"Star Guy Jr.","WR",1,2,10000,9000\n"Mid Guy","RB",50,40,4000,4500\n"Deep Guy","TE",150,150,500,400\n'
    PICKS = '"player","pos","ecr_1qb","ecr_2qb"\n"2027 Early 1st","PICK",50,40\n"2027 Late 1st","PICK",150,150\n"2026 Pick 1.01","PICK",1,2\n'

    def setUp(self):
        self.snap = sync_trade_values.Snapshot(self.PLAYERS, self.PICKS)

    def test_players_and_drafted_picks(self):
        d = sync_trade_values.dt.date(2026, 10, 1)
        self.assertEqual(sync_trade_values.item_value("Star Guy (WR)", self.snap, d), 10000)
        self.assertEqual(sync_trade_values.item_value("2024 Round 1st Pick (originally from A (a)) -> Resulted in drafting: Mid Guy (RB)", self.snap, d), 4000)
        self.assertEqual(sync_trade_values.item_value("Unknown Guy (K)", self.snap, d), 0)

    def test_picks_by_draft_state(self):
        d = sync_trade_values.dt.date(2026, 10, 1)
        # 2027 1st: average of Early (ECR 50 -> 4000) and Late (ECR 150 -> 500)
        self.assertEqual(sync_trade_values.item_value("2027 Round 1st Pick (originally from A (a))", self.snap, d), 2250)
        # 2026 draft is done by October and no player was recorded
        self.assertEqual(sync_trade_values.item_value("2026 Round 1st Pick", self.snap, d), 0)

    def test_superflex_columns(self):
        snap = sync_trade_values.Snapshot(self.PLAYERS, self.PICKS, superflex=True)
        self.assertEqual(snap.player("Mid Guy"), 4500)

    def test_items_and_marks(self):
        bd = "A received: [X (WR), 2027 Round 1st Pick (originally from B (b))] <---> B received: [Y (RB)]"
        self.assertEqual(sync_trade_values.trade_items(bd), ["X (WR)", "2027 Round 1st Pick (originally from B (b))", "Y (RB)"])
        master = {"L": [SEC("TRADE HISTORY"), ["Season"], ["2023", "10/1/2023", "Week 5", "A & B", bd, "", ""],
                        ["2024", "10/1/2024", "Week 5", "A & B", bd, "", ""]]}
        with mock.patch.object(sync_trade_values.league_config, 'leagues', return_value=[]):
            due = list(sync_trade_values.due_trades(master, sync_trade_values.dt.date(2026, 10, 26)))
        self.assertEqual([(k.split('||')[2], m.isoformat()) for k, _, _, m in due], [("10/1/2023", "2026-10-01")])

    def test_2019_ranking_only_snapshot(self):
        players = 'mergename,pos,dynoECR,dyno2QBECR\nOld Star,WR,1,3\nOld Mid,RB,100,90\n'
        picks = 'mergename,pos,dynoECR,dyno2QBECR\n2019 Pick 14,PICK,50,40\n2020 1st,PICK,150,150\n'
        snap = sync_trade_values.Snapshot(players, picks, reference_curve=self.snap.curve)
        self.assertEqual(snap.player("Old Star"), 10000)
        self.assertEqual(snap.player("Old Mid"), 2250)  # ECR 100 halfway between 50 (4000) and 150 (500)
        self.assertEqual(snap.pick(2019, 2), 4000)  # overall pick 14 is a 2nd-rounder
        self.assertEqual(snap.pick(2020, 1), 500)
