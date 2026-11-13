"""Unit tests for the score check (scripts/check_scores.py). Run with: python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import check_scores as cs  # noqa: E402

SEC = lambda title: [f"--- {title} ---", "", "", "", "", "", ""]  # noqa: E731
USERS = [{'user_id': 'u1', 'display_name': 'alice', 'metadata': {'team_name': 'Aces'}},
         {'user_id': 'u2', 'display_name': 'bob', 'metadata': {}}]


def rosters(a_pf=250.5, b_pf=240.25):
    def r(rid, uid, w, l, pf):
        return {'roster_id': rid, 'owner_id': uid,
                'settings': {'wins': w, 'losses': l, 'ties': 0, 'fpts': int(pf), 'fpts_decimal': round((pf % 1) * 100)}}
    return [r(1, 'u1', 2, 0, a_pf), r(2, 'u2', 0, 2, b_pf)]


def saved(open_week='3', week2=("120.25", "110.00")):
    return [SEC("LEAGUE PROFILE"), ["League ID", "L1"], ["Current Season", "2026"], ["Open Week", open_week],
            SEC("PAST SEASONS STANDINGS & CHAMPIONS"), ["Season", "Team / Manager"],
            ["2026", "Aces (alice)", "2-0", "250.50", "Regular Season", "", ""],
            ["2026", "bob", "0-2", "240.25", "Regular Season", "", ""],
            ["2025", "bob", "9-5", "1500.00", "Champion", "", ""],
            SEC("ALL-TIME MATCHUPS & SCHEDULE (ALL SEASONS)"), ["Season", "Week"],
            ["2026", "Week 1", "1", "Aces (alice)", "130.25", "bob", "130.25"],
            ["2026", "Week 2", "1", "bob", week2[1], "Aces (alice)", week2[0]],
            ["2026", "Week 3", "1", "Aces (alice)", "50.00", "bob", "10.00"]]


def fake_sleeper(week_points, rost=None):
    def fetch(url):
        if url.endswith('/rosters'):
            return rost or rosters()
        if url.endswith('/users'):
            return USERS
        if '/matchups/' in url:
            wk = int(url.rsplit('/', 1)[1])
            a, b = week_points.get(wk, (0, 0))
            return [{'matchup_id': 1, 'roster_id': 1, 'points': a}, {'matchup_id': 1, 'roster_id': 2, 'points': b},
                    {'matchup_id': None, 'roster_id': 3, 'points': 0}]
        return {'season': '2026'}
    return fetch


CFG = {'name': 'Test League', 'id': 'L1'}
GOOD = {1: (130.25, 130.25), 2: (120.25, 110.0), 3: (999, 999)}


class ScoreCheck(unittest.TestCase):
    def test_matching_data_passes_and_open_week_skipped(self):
        name, weeks, problems, note = cs.check_league(CFG, {'Test League': saved()}, fake_sleeper(GOOD))
        self.assertEqual((weeks, problems, note), ([1, 2], [], ""))

    def test_score_difference_flagged(self):
        pts = {**GOOD, 2: (122.75, 110.0)}
        _, _, problems, _ = cs.check_league(CFG, {'Test League': saved()}, fake_sleeper(pts))
        self.assertEqual(problems, ["Week 2: Aces (alice) saved 120.25, Sleeper says 122.75"])

    def test_missing_game_flagged(self):
        master = {'Test League': [r for r in saved() if r[1] != "Week 2"]}
        _, _, problems, _ = cs.check_league(CFG, master, fake_sleeper(GOOD))
        self.assertEqual(len(problems), 1)
        self.assertIn("missing from the saved data", problems[0])

    def test_standings_points_for_flagged(self):
        _, _, problems, _ = cs.check_league(CFG, {'Test League': saved()}, fake_sleeper(GOOD, rosters(b_pf=241.25)))
        self.assertEqual(problems, ["Standings: bob Points For saved 240.25, Sleeper says 241.25"])

    def test_no_open_week_checks_every_week(self):
        self.assertEqual(cs.finished_weeks({'Open Week': ''}), list(range(1, 18)))

    def test_other_season_skipped(self):
        master = {'Test League': [["Current Season", "2025"] if r[0] == "Current Season" else r for r in saved()]}
        _, weeks, problems, note = cs.check_league(CFG, master, fake_sleeper(GOOD))
        self.assertEqual((weeks, problems), ([], []))
        self.assertIn("skipped", note)

    def test_report_mentions_differences(self):
        report = cs.build_report([("A", [1, 2], ["Week 2: x saved 1.00, Sleeper says 2.00"], "")])
        self.assertIn("**1** difference", report)
        self.assertIn("What to do", report)


if __name__ == '__main__':
    unittest.main()
