"""生產線的煙霧測試。

cron 是無人看管的，推壞了不會有人立刻發現，所以每次 push 都跑一遍：
文案產得出來、圖畫得出來、課綱不重複、免責聲明沒被拿掉。
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from square import compose, config, imagegen, market, topics, tracker  # noqa: E402


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = config.load()
        cls.snap = market.fetch(cls.cfg, offline=True)

    def test_every_kind_builds(self):
        for kind in compose.BUILDERS:
            with self.subTest(kind=kind):
                post = compose.build(kind, self.cfg, self.snap)
                self.assertTrue(post.title.strip())
                self.assertGreater(len(post.body), 100, "文案太短，可能是資料沒帶進來")
                self.assertTrue(post.hashtags)

    def test_disclaimer_always_present(self):
        disclaimer = self.cfg.get("content", "disclaimer")
        for kind in compose.BUILDERS:
            with self.subTest(kind=kind):
                md = compose.build(kind, self.cfg, self.snap).to_markdown(self.cfg)
                self.assertIn(disclaimer, md)

    def test_referral_only_on_configured_kinds(self):
        allowed = set(self.cfg.get("brand", "referral_on", default=[]))
        url = self.cfg.get("brand", "referral_url")
        for kind in compose.BUILDERS:
            md = compose.build(kind, self.cfg, self.snap).to_markdown(self.cfg)
            with self.subTest(kind=kind):
                self.assertEqual(url in md, kind in allowed)

    def test_all_kinds_render_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in compose.BUILDERS:
                post = compose.build(kind, self.cfg, self.snap)
                out = Path(tmp) / f"{kind}.png"
                imagegen.render(self.cfg, post, self.snap, out)
                with self.subTest(kind=kind):
                    self.assertGreater(out.stat().st_size, 10_000, "圖檔太小，可能是空白圖")

    def test_every_topic_renders_without_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(len(topics.TOPICS)):
                post = compose.education(self.cfg, self.snap, index=i)
                imagegen.render(self.cfg, post, self.snap, Path(tmp) / f"t{i}.png")

    def test_topic_ids_and_titles_unique(self):
        ids = [t.id for t in topics.TOPICS]
        titles = [t.title for t in topics.TOPICS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(titles), len(set(titles)))

    def test_topic_rotation_covers_everything_before_repeating(self):
        seen = {topics.pick(i).id for i in range(len(topics.TOPICS))}
        self.assertEqual(len(seen), len(topics.TOPICS))

    def test_education_index_only_counts_scheduled_days(self):
        epoch = compose.EDU_EPOCH
        self.assertEqual(compose.education_index(epoch), 0)
        # 起算日是週一，隔天週二不是教育日，index 只 +1（來自週一本身）
        self.assertEqual(compose.education_index(epoch + dt.timedelta(days=1)), 1)
        self.assertEqual(compose.education_index(epoch + dt.timedelta(days=2)), 1)
        self.assertEqual(compose.education_index(epoch + dt.timedelta(days=7)), 3)

    def test_weekly_schedule_covers_seven_days(self):
        counts = {}
        for offset in range(7):
            day = compose.EDU_EPOCH + dt.timedelta(days=offset)
            for kind in compose.kinds_for(day):
                counts[kind] = counts.get(kind, 0) + 1
        self.assertEqual(counts["morning_brief"], 7)
        self.assertEqual(counts["education"], 3)
        self.assertEqual(counts["data_watch"], 3)
        self.assertEqual(counts["weekly"], 1)

    def test_tracker_roundtrip_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config.load()
            # 改寫路徑函式，避免測試污染真正的追蹤表
            original = tracker.path_for

            def fake_path(_cfg):
                return Path(tmp) / tracker.FILENAME

            tracker.path_for = fake_path  # type: ignore[assignment]
            try:
                tracker.append(cfg, tracker.Entry(followers=120, impressions=5000, posts_published=2))
                rows = tracker.read(cfg)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].followers, 120)
                self.assertIn("粉絲數", tracker.status(cfg))
            finally:
                tracker.path_for = original  # type: ignore[assignment]

    def test_no_price_predictions_in_templates(self):
        """文案不該出現承諾報酬或喊單的字眼，這是合規紅線。

        只擋「作者在做出承諾」的措辭。像「保證金」「保證收益（在講詐騙話術）」
        這種正當用法不在此列，所以比對的是完整詞組而不是單字。
        """
        banned = [
            "保證獲利", "保證賺", "穩賺", "包賺", "必漲", "必跌",
            "一定會漲", "一定會跌", "推薦買入", "建議買入", "目標價", "帶單",
        ]
        bodies = {k: compose.build(k, self.cfg, self.snap).body for k in compose.BUILDERS}
        # 教育貼文的風險最高，整份課綱都要掃過，不能只掃今天輪到的那篇
        for i, topic in enumerate(topics.TOPICS):
            bodies[f"education:{topic.id}"] = compose.education(self.cfg, self.snap, index=i).body
        for label, body in bodies.items():
            for word in banned:
                with self.subTest(source=label, word=word):
                    self.assertNotIn(word, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
