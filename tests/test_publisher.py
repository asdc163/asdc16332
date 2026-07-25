"""發布路徑的測試。

發文是不可逆的對外動作，所以這裡的重點不是「能不能發成功」，
而是「不該發的時候會不會發出去」：重複發、逾時後重送、錯誤時誤記帳。
全部用假的 HTTP 層，不會碰到真的幣安端點。
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from square import cli, config, ledger, publisher  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@contextmanager
def fake_http(handler):
    """handler(url, method, body) -> FakeResponse 或 raise。記錄所有呼叫。"""
    calls: list[dict] = []

    def _urlopen(req, timeout=None):
        record = {
            "url": req.full_url,
            "method": req.get_method(),
            "headers": {k.lower(): v for k, v in req.headers.items()},
            "body": json.loads(req.data.decode()) if req.data and req.get_method() == "POST" else req.data,
        }
        calls.append(record)
        return handler(record)

    with mock.patch("square.publisher.urllib.request.urlopen", _urlopen):
        yield calls


def ok(data=None):
    return FakeResponse({"code": "000000", "data": data or {}})


class ContentBodyTest(unittest.TestCase):
    def test_text_only_post(self):
        body = publisher.SquareClient._content_body("嗨", [], None)
        self.assertEqual(body, {"contentType": 1, "bodyTextOnly": "嗨"})

    def test_image_post_uses_content_type_1(self):
        body = publisher.SquareClient._content_body("嗨", ["u1"], None)
        self.assertEqual(body, {"contentType": 1, "bodyTextOnly": "嗨", "imageList": ["u1"]})

    def test_image_list_capped_at_four(self):
        body = publisher.SquareClient._content_body("嗨", [f"u{i}" for i in range(9)], None)
        self.assertEqual(len(body["imageList"]), 4)

    def test_article_uses_content_type_2_with_cover(self):
        body = publisher.SquareClient._content_body("內文", ["cover-url"], "標題")
        self.assertEqual(body["contentType"], 2)
        self.assertEqual(body["title"], "標題")
        self.assertEqual(body["cover"], "cover-url")
        self.assertNotIn("imageList", body)


class KeyTest(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict("os.environ", {publisher.KEY_ENV: "  abc123  "}):
            self.assertEqual(publisher.load_key(), "abc123")

    def test_missing_key_raises_with_guidance(self):
        with mock.patch.dict("os.environ", {publisher.KEY_ENV: ""}), \
             mock.patch.object(publisher, "KEY_FILE", Path("/nonexistent/key")):
            with self.assertRaises(publisher.MissingKeyError) as ctx:
                publisher.load_key()
            self.assertIn("creator-center", str(ctx.exception))

    def test_redact_never_exposes_whole_key(self):
        key = "0123456789abcdef0123456789abcdef"  # 假金鑰，不要放真的
        red = publisher.redact(key)
        self.assertNotIn(key, red)
        self.assertLess(len(red), len(key))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.client = publisher.SquareClient("k")

    def test_sends_required_headers(self):
        with fake_http(lambda r: ok({"id": "1"})) as calls:
            self.client.publish("嗨")
        headers = calls[0]["headers"]
        self.assertEqual(headers["x-square-openapi-key"], "k")
        self.assertEqual(headers["Clienttype".lower()], "binanceSkill")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertTrue(calls[0]["url"].endswith("/v1/public/pgc/openApi/content/add"))

    def test_business_error_code_surfaces_hint(self):
        def handler(_):
            return FakeResponse({"code": "220009", "message": "limit"})

        with fake_http(handler):
            with self.assertRaises(publisher.PublishError) as ctx:
                self.client.publish("嗨")
        self.assertEqual(ctx.exception.code, "220009")
        self.assertIn("100 篇", str(ctx.exception))
        self.assertFalse(ctx.exception.is_retryable, "業務錯誤重試會有重複發文風險")

    def test_gateway_timeout_counts_as_sent_and_is_not_retried(self):
        """504 代表已送達但沒回 id。當成失敗重送就會發出兩篇。"""
        def handler(_):
            raise urllib.error.HTTPError("u", 504, "Gateway Timeout", {}, io.BytesIO(b""))

        with fake_http(handler) as calls:
            result = self.client.publish("嗨")
        self.assertEqual(result["publishStatus"], "success_without_post_id")
        self.assertEqual(len(calls), 1, "504 之後不可以再打一次")

    def test_non_json_response_is_reported(self):
        with fake_http(lambda r: FakeResponse(b"<html>502</html>")):
            with self.assertRaises(publisher.PublishError) as ctx:
                self.client.publish("嗨")
        self.assertIn("不是 JSON", str(ctx.exception))


class ImageUploadTest(unittest.TestCase):
    def setUp(self):
        self.client = publisher.SquareClient("k")
        self.tmp = tempfile.TemporaryDirectory()
        self.img = Path(self.tmp.name) / "card.png"
        self.img.write_bytes(b"\x89PNG fake bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def _handler(self, statuses):
        seq = iter(statuses)

        def handler(record):
            if record["url"].endswith("/image/presignedUrl"):
                return ok({"presignedUrl": "https://s3.example/put", "fileTicket": "T1"})
            if record["method"] == "PUT":
                return FakeResponse(b"", status=200)
            if record["url"].endswith("/image/imageStatus"):
                return ok(next(seq))
            raise AssertionError(f"未預期的呼叫 {record['url']}")

        return handler

    def test_happy_path_returns_image_url(self):
        with fake_http(self._handler([{"status": 1, "imageUrl": "https://img/1.png"}])) as calls:
            url = self.client.upload_image(self.img)
        self.assertEqual(url, "https://img/1.png")
        self.assertEqual(calls[0]["body"], {"imageName": "card.png"})
        self.assertEqual(calls[1]["method"], "PUT")
        self.assertEqual(calls[1]["headers"]["content-type"], "image/png")
        self.assertEqual(calls[2]["body"], {"fileTicket": "T1"})

    def test_polls_until_ready(self):
        statuses = [{"status": 0}, {"status": 0}, {"status": 1, "imageUrl": "https://img/2.png"}]
        with mock.patch("square.publisher.time.sleep"):
            with fake_http(self._handler(statuses)):
                self.assertEqual(self.client.upload_image(self.img), "https://img/2.png")

    def test_processing_failure_raises(self):
        with fake_http(self._handler([{"status": 2, "failedReason": "圖片違規"}])):
            with self.assertRaises(publisher.PublishError) as ctx:
                self.client.upload_image(self.img)
        self.assertIn("圖片違規", str(ctx.exception))

    def test_timeout_after_max_attempts(self):
        with mock.patch("square.publisher.time.sleep"):
            with fake_http(self._handler([{"status": 0}] * publisher.IMAGE_POLL_ATTEMPTS)):
                with self.assertRaises(publisher.PublishError) as ctx:
                    self.client.upload_image(self.img)
        self.assertIn("逾時", str(ctx.exception))

    def test_dry_run_never_touches_network(self):
        client = publisher.SquareClient("k", dry_run=True)
        with fake_http(lambda r: AssertionError("不該有任何請求")) as calls:
            client.upload_image(self.img)
            client.publish("嗨", images=["x"])
        self.assertEqual(calls, [])


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config.load()
        self.patcher = mock.patch.object(
            ledger, "path_for", lambda _c: Path(self.tmp.name) / ledger.FILENAME
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_record_then_detected_as_published(self):
        book = ledger.load(self.cfg)
        self.assertFalse(ledger.is_published(book, "2026-07-25", "morning-brief"))
        ledger.record(self.cfg, book, "2026-07-25", "morning-brief", content_id="9")
        self.assertTrue(ledger.is_published(ledger.load(self.cfg), "2026-07-25", "morning-brief"))

    def test_counts_are_scoped_to_the_day(self):
        book = ledger.load(self.cfg)
        ledger.record(self.cfg, book, "2026-07-25", "a")
        ledger.record(self.cfg, book, "2026-07-25", "b")
        ledger.record(self.cfg, book, "2026-07-26", "c")
        self.assertEqual(ledger.count_on(book, "2026-07-25"), 2)

    def test_corrupt_ledger_refuses_to_continue(self):
        (Path(self.tmp.name) / ledger.FILENAME).write_text("{ broken", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            ledger.load(self.cfg)


class FrontMatterTest(unittest.TestCase):
    def test_parses_metadata_and_strips_it_from_body(self):
        raw = '---\nkind: "education"\ntitle: "標題"\nimage: "a.png"\n---\n\n內文第一行\n\n內文第二行\n'
        meta, body = cli._parse_front_matter(raw)
        self.assertEqual(meta["kind"], "education")
        self.assertEqual(meta["title"], "標題")
        self.assertTrue(body.startswith("內文第一行"))
        self.assertNotIn("---", body)
        self.assertNotIn("kind:", body)

    def test_document_without_front_matter_passes_through(self):
        meta, body = cli._parse_front_matter("純內文")
        self.assertEqual(meta, {})
        self.assertEqual(body, "純內文")


class PublishDayTest(unittest.TestCase):
    """整條發布流程：不重複發、失敗不記帳。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = config.load()
        self.day = dt.date(2026, 7, 25)

        out = root / "out" / self.day.isoformat()
        out.mkdir(parents=True)
        (out / "morning-brief.md").write_text(
            '---\nkind: "morning_brief"\ntitle: "早報"\nimage: "morning-brief.png"\n---\n\n今天的行情。\n',
            encoding="utf-8",
        )
        (out / "morning-brief.png").write_bytes(b"\x89PNG fake")
        (out / "manifest.json").write_text(json.dumps({
            "date": self.day.isoformat(),
            "posts": [{"kind": "morning_brief", "markdown": "morning-brief.md",
                       "image": "morning-brief.png", "title": "早報"}],
        }), encoding="utf-8")

        self.patchers = [
            mock.patch.object(type(self.cfg), "out_dir", property(lambda _s: root / "out")),
            mock.patch.object(ledger, "path_for", lambda _c: root / ledger.FILENAME),
            mock.patch("square.tracker.path_for", lambda _c: root / "tracking.csv"),
            mock.patch.dict("os.environ", {publisher.KEY_ENV: "testkey"}),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def _handler(self, publish_result=None):
        def handler(record):
            if record["url"].endswith("/image/presignedUrl"):
                return ok({"presignedUrl": "https://s3/put", "fileTicket": "T"})
            if record["method"] == "PUT":
                return FakeResponse(b"", status=200)
            if record["url"].endswith("/image/imageStatus"):
                return ok({"status": 1, "imageUrl": "https://img/x.png"})
            if record["url"].endswith("/content/add"):
                if isinstance(publish_result, Exception):
                    raise publish_result
                return ok(publish_result or {"id": "123456"})
            raise AssertionError(record["url"])

        return handler

    def test_publishes_once_and_records(self):
        with fake_http(self._handler()) as calls:
            rc = cli._publish_day(self.cfg, self.day)
        self.assertEqual(rc, 0)
        add = [c for c in calls if c["url"].endswith("/content/add")]
        self.assertEqual(len(add), 1)
        self.assertEqual(add[0]["body"]["contentType"], 1)
        self.assertEqual(add[0]["body"]["imageList"], ["https://img/x.png"])
        self.assertIn("今天的行情。", add[0]["body"]["bodyTextOnly"])
        self.assertTrue(ledger.is_published(ledger.load(self.cfg), self.day.isoformat(), "morning-brief"))

    def test_second_run_does_not_repost(self):
        with fake_http(self._handler()):
            cli._publish_day(self.cfg, self.day)
        with fake_http(self._handler()) as calls:
            rc = cli._publish_day(self.cfg, self.day)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [], "已發過的貼文不可以再送出任何請求")

    def test_failure_is_not_recorded_so_it_can_be_retried(self):
        err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b"{}"))
        with fake_http(self._handler(err)):
            rc = cli._publish_day(self.cfg, self.day)
        self.assertEqual(rc, 1)
        self.assertFalse(ledger.is_published(ledger.load(self.cfg), self.day.isoformat(), "morning-brief"))

    def test_gateway_timeout_is_recorded_to_prevent_duplicate(self):
        err = urllib.error.HTTPError("u", 504, "timeout", {}, io.BytesIO(b""))
        with fake_http(self._handler(err)):
            rc = cli._publish_day(self.cfg, self.day)
        self.assertEqual(rc, 0)
        self.assertTrue(
            ledger.is_published(ledger.load(self.cfg), self.day.isoformat(), "morning-brief"),
            "504 已送達，必須記帳，否則下次排程會重複發文",
        )

    def test_dry_run_sends_nothing_and_records_nothing(self):
        with fake_http(lambda r: AssertionError("不該有請求")) as calls:
            rc = cli._publish_day(self.cfg, self.day, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertFalse(ledger.is_published(ledger.load(self.cfg), self.day.isoformat(), "morning-brief"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
