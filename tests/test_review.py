"""每週檢視與數據回報的測試。

檢視報告會驅動策略調整，所以重點是：
沒有數據時不能編結論，有數據時建議要指向真正最弱的那一層。
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from square import config, intake, ledger, review, tracker  # noqa: E402


class IntakeParseTest(unittest.TestCase):
    def test_english_colon_form(self):
        got = intake.parse("followers: 1250\nimpressions: 8400\nclicks: 96\nsignups: 4\ncommission: 23.5")
        self.assertEqual(got["followers"], 1250)
        self.assertEqual(got["impressions"], 8400)
        self.assertEqual(got["profile_clicks"], 96)
        self.assertEqual(got["referral_signups"], 4)
        self.assertAlmostEqual(got["commission_usdt"], 23.5)

    def test_chinese_freeform(self):
        got = intake.parse("這週粉絲數 1250，曝光 8,400，進個人頁 96 次，註冊 4 個，返佣 23.5 USDT")
        self.assertEqual(got["followers"], 1250)
        self.assertEqual(got["impressions"], 8400)
        self.assertEqual(got["profile_clicks"], 96)
        self.assertEqual(got["referral_signups"], 4)
        self.assertAlmostEqual(got["commission_usdt"], 23.5)

    def test_thousands_separator_and_equals(self):
        got = intake.parse("impressions=1,234,567")
        self.assertEqual(got["impressions"], 1234567)

    def test_fullwidth_colon(self):
        self.assertEqual(intake.parse("粉絲數：888")["followers"], 888)

    def test_partial_input_only_returns_what_was_given(self):
        got = intake.parse("followers: 500")
        self.assertEqual(got, {"followers": 500})
        self.assertNotIn("impressions", got)

    def test_empty_template_yields_nothing(self):
        """檢視 issue 附的空白樣板被原樣貼回來時，不可以寫入一排 0。"""
        got = intake.parse("followers: \nimpressions: \nclicks: \nsignups: \ncommission: ")
        self.assertEqual(got, {})

    def test_prose_without_numbers_yields_nothing(self):
        self.assertEqual(intake.parse("這週還沒看後台，之後補"), {})

    def test_negative_values_rejected(self):
        self.assertEqual(intake.parse("followers: -5"), {})

    def test_longer_alias_wins(self):
        """「粉絲數」與「粉絲」都在別名裡，不能因為短的先比中而取錯位置。"""
        self.assertEqual(intake.parse("粉絲數 1250")["followers"], 1250)


class PublishHealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config.load()
        self.patcher = mock.patch.object(
            ledger, "path_for", lambda _c: Path(self.tmp.name) / ledger.FILENAME
        )
        self.patcher.start()
        # 上線日設在視窗之前，讓整週都納入對帳
        self.live = mock.patch.object(review, "_live_since", lambda _c: dt.date(2026, 1, 1))
        self.live.start()

    def tearDown(self):
        self.live.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    def test_expected_count_matches_weekly_schedule(self):
        window = review.week_ending(dt.date(2026, 8, 2))  # 週日
        health = review.publish_health(self.cfg, window)
        # 每日早報 7 + 教育 3 + 數據觀察 3 + 週報 1
        self.assertEqual(health.expected, 14)
        self.assertEqual(health.actual, 0)

    def test_recorded_posts_count_as_published(self):
        window = review.week_ending(dt.date(2026, 8, 2))
        book = ledger.load(self.cfg)
        for day in window.days:
            ledger.record(self.cfg, book, day.isoformat(), "morning-brief")
        health = review.publish_health(self.cfg, window)
        self.assertEqual(health.actual, 7)
        self.assertFalse(health.healthy)
        self.assertEqual(len(health.missing), 7)

    def test_before_go_live_is_not_counted_as_missing(self):
        with mock.patch.object(review, "_live_since", lambda _c: dt.date(2026, 8, 1)):
            window = review.week_ending(dt.date(2026, 8, 2))
            health = review.publish_health(self.cfg, window)
        # 只剩 8/1 與 8/2 兩天納入
        self.assertLess(health.expected, 14)
        self.assertGreater(health.expected, 0)


class RecommendationTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()

    def _healthy(self):
        return review.PublishHealth(expected=14, actual=14)

    def test_broken_pipeline_is_the_first_priority(self):
        health = review.PublishHealth(expected=14, actual=3, missing=["07/20 education"])
        funnel = review.Funnel(has_data=True, impressions=50000, clicks=900, signups=30,
                               followers_start=100, followers_end=400)
        recs = review.recommendations(self.cfg, health, funnel)
        self.assertIn("先修管線", recs[0])

    def test_no_growth_data_refuses_to_diagnose(self):
        recs = review.recommendations(self.cfg, self._healthy(), review.Funnel(has_data=False))
        self.assertEqual(len(recs), 1)
        self.assertIn("缺成長數據", recs[0])

    def test_low_reach_is_flagged_as_the_bottleneck(self):
        funnel = review.Funnel(has_data=True, posts=14, impressions=1000, clicks=5,
                               followers_start=100, followers_end=110)
        recs = review.recommendations(self.cfg, self._healthy(), funnel)
        self.assertTrue(any("觸及是目前的瓶頸" in r for r in recs))

    def test_good_reach_but_low_click_rate_targets_the_hook(self):
        funnel = review.Funnel(has_data=True, posts=14, impressions=100000, clicks=200,
                               signups=5, followers_start=100, followers_end=140)
        recs = review.recommendations(self.cfg, self._healthy(), funnel)
        self.assertTrue(any("不點進個人頁" in r for r in recs))

    def test_clicks_but_zero_signups_points_at_the_link_placement(self):
        funnel = review.Funnel(has_data=True, posts=14, impressions=100000, clicks=3000,
                               signups=0, followers_start=100, followers_end=300)
        recs = review.recommendations(self.cfg, self._healthy(), funnel)
        self.assertTrue(any("動線斷了" in r for r in recs))

    def test_flat_followers_shifts_content_mix(self):
        funnel = review.Funnel(has_data=True, posts=14, impressions=100000, clicks=2000,
                               signups=60, commission=150, followers_start=500, followers_end=500)
        recs = review.recommendations(self.cfg, self._healthy(), funnel)
        self.assertTrue(any("沒有淨增長" in r for r in recs))

    def test_slow_growth_calls_the_goal_unrealistic(self):
        funnel = review.Funnel(has_data=True, posts=14, impressions=100000, clicks=2000,
                               signups=60, commission=150, followers_start=100, followers_end=105)
        recs = review.recommendations(self.cfg, self._healthy(), funnel)
        self.assertTrue(any("靠自然增長到不了" in r for r in recs))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config.load()
        self.patchers = [
            mock.patch.object(ledger, "path_for", lambda _c: Path(self.tmp.name) / ledger.FILENAME),
            mock.patch.object(tracker, "path_for", lambda _c: Path(self.tmp.name) / tracker.FILENAME),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_report_without_data_asks_for_it_and_makes_no_claims(self):
        report = review.build_report(self.cfg, dt.date(2026, 8, 2))
        self.assertIn("每週檢視", report)
        self.assertIn("followers:", report, "沒有數據時要附上可直接填的樣板")
        self.assertNotIn("轉換率偏低", report)

    def test_report_with_data_renders_the_funnel_table(self):
        tracker.append(self.cfg, tracker.Entry(
            date="2026-07-30", followers=1250, impressions=8400,
            profile_clicks=96, referral_signups=4, commission_usdt=23.5,
        ))
        report = review.build_report(self.cfg, dt.date(2026, 8, 2))
        self.assertIn("| 曝光 | 8,400 |", report)
        self.assertIn("1,250", report)
        self.assertIn("23.50", report)

    def test_report_lists_next_weeks_topics(self):
        report = review.build_report(self.cfg, dt.date(2026, 8, 2))
        self.assertIn("下週教育系列排程", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
