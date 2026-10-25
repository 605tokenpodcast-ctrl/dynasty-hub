"""Unit tests for the sync scripts' pure logic. Run with: python -m unittest discover tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import sync_fleaflicker  # noqa: E402
import sync_leagues  # noqa: E402
import build_rso  # noqa: E402

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


class RsoParsing(unittest.TestCase):
    def test_player_names(self):
        self.assertEqual(build_rso.clean_player("Michael Wilson ARI  (WR)"), ("Michael Wilson", "WR"))
        self.assertEqual(build_rso.clean_player("Smith-Njigba, Jaxon SEA (WR)"), ("Jaxon Smith-Njigba", "WR"))
        self.assertEqual(build_rso.clean_player("Erick All Jr. CIN (TE)"), ("Erick All Jr.", "TE"))

    def test_picks_and_weeks(self):
        self.assertEqual(build_rso.ordinal_pick("2027 2nd Round Draft Pick"), ("2027", "2nd"))
        self.assertEqual(build_rso.ordinal_pick("Michael Wilson ARI (WR)"), (None, None))
        from datetime import date
        self.assertEqual(build_rso.week_of(date(2026, 5, 7)), "Week 1")
        self.assertEqual(build_rso.week_of(date(2026, 9, 16)), "Week 1")
        self.assertEqual(build_rso.week_of(date(2026, 10, 18)), "Week 6")
        self.assertEqual(build_rso.week_of(date(2026, 10, 21)), "Week 6")

    def test_description_keeps_its_separators(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build_rso, "SNAP", d):
            with open(os.path.join(d, "t.psv"), "w", encoding="utf-8") as f:
                f.write("id|description\n1|Dropped A NO (WR) || Add Player to Roster B SEA (RB)\n")
            self.assertEqual(build_rso.read_psv("t.psv")[0]["description"],
                             "Dropped A NO (WR) || Add Player to Roster B SEA (RB)")


if __name__ == '__main__':
    unittest.main()
