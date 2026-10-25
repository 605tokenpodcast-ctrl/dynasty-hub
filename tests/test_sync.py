"""Unit tests for the sync scripts' pure logic. Run with: python -m unittest discover tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import sync_fleaflicker  # noqa: E402
import sync_leagues  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
