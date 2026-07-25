"""指令列進入點。

  python -m square generate            產生今天該發的所有貼文草稿與配圖
  python -m square generate --publish  產生後直接發布到幣安廣場
  python -m square publish             發布 out/ 裡今天還沒發過的貼文
  python -m square publish --dry-run   只印出將送出的內容，不真的發
  python -m square preview             只印文案不存檔
  python -m square track --followers 1234 --commission 18.5
  python -m square status              看目標進度與漏斗診斷
  python -m square topics              列出教育課綱與輪替順序

發布需要環境變數 BINANCE_SQUARE_OPENAPI_KEY（廣場創作者中心產生的金鑰）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import compose, config, imagegen, ledger, market, publisher, topics, tracker


def _snapshot(cfg, offline: bool):
    try:
        return market.fetch(cfg, offline=offline)
    except market.MarketError as exc:
        if offline:
            raise
        print(f"[警告] 即時行情取得失敗（{exc}），改用離線示意資料。", file=sys.stderr)
        return market.fetch(cfg, offline=True)


def cmd_generate(args, cfg) -> int:
    snap = _snapshot(cfg, args.offline)
    day = snap.generated_at.date()
    kinds = [args.kind] if args.kind else compose.kinds_for(day)

    out_root = cfg.out_dir / day.isoformat()
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = []

    for kind in kinds:
        post = compose.build(kind, cfg, snap)
        md_path = out_root / f"{post.slug}.md"
        img_path = out_root / f"{post.slug}.png"

        imagegen.render(cfg, post, snap, img_path)

        front = [
            "---",
            f'kind: "{post.kind}"',
            f'title: "{post.title}"',
            f'date: "{snap.generated_at.isoformat()}"',
            f'image: "{img_path.name}"',
            f"live_data: {str(not snap.offline).lower()}",
            "status: draft",
            "---",
            "",
        ]
        md_path.write_text("\n".join(front) + post.to_markdown(cfg), encoding="utf-8")

        manifest.append({"kind": kind, "markdown": md_path.name, "image": img_path.name, "title": post.title})
        print(f"  ✓ {kind:<14} {md_path.name}  +  {img_path.name}")

    (out_root / "manifest.json").write_text(
        json.dumps(
            {"date": day.isoformat(), "live_data": not snap.offline, "posts": manifest},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n產出目錄：{out_root}")
    if args.publish:
        print()
        return _publish_day(cfg, day, kinds=kinds, dry_run=args.dry_run)
    print("要發布：python -m square publish")
    return 0


# ---------------------------------------------------------------- 發布

def _parse_front_matter(text: str) -> tuple[dict, str]:
    """回傳 (front matter 欄位, 內文)。格式由 cmd_generate 寫入，很單純。"""
    if not text.startswith("---\n"):
        return {}, text
    _, _, rest = text.partition("---\n")
    block, sep, body = rest.partition("---\n")
    if not sep:
        return {}, text
    meta = {}
    for line in block.splitlines():
        name, _, value = line.partition(":")
        if not _:
            continue
        meta[name.strip()] = value.strip().strip('"')
    return meta, body.lstrip("\n")


def _publish_day(cfg, day: dt.date, kinds: list[str] | None = None, dry_run: bool = False) -> int:
    out_root = cfg.out_dir / day.isoformat()
    manifest_path = out_root / "manifest.json"
    if not manifest_path.exists():
        print(f"[錯誤] 找不到 {manifest_path}，請先執行 generate。", file=sys.stderr)
        return 1

    entries = json.loads(manifest_path.read_text(encoding="utf-8")).get("posts", [])
    if kinds:
        entries = [e for e in entries if e["kind"] in kinds]
    if not entries:
        print("沒有符合條件的貼文。")
        return 0

    try:
        api_key = publisher.load_key()
    except publisher.MissingKeyError as exc:
        if not dry_run:
            print(f"[錯誤] {exc}", file=sys.stderr)
            return 1
        api_key = "dry-run"

    client = publisher.SquareClient(api_key, dry_run=dry_run)
    book = ledger.load(cfg)
    article_kinds = set(cfg.get("publish", "article_kinds", default=[]))
    day_str = day.isoformat()

    mode = "（乾跑，不會真的送出）" if dry_run else f"（金鑰 {publisher.redact(api_key)}）"
    print(f"發布 {day_str} 的貼文 {mode}")

    results: list[publisher.PublishResult] = []
    for entry in entries:
        slug = Path(entry["markdown"]).stem
        kind = entry["kind"]

        if ledger.is_published(book, day_str, slug):
            print(f"  · {kind:<14} 已發過，跳過")
            results.append(publisher.PublishResult(slug, kind, "skipped"))
            continue

        meta, body = _parse_front_matter((out_root / entry["markdown"]).read_text(encoding="utf-8"))
        title = meta.get("title") if kind in article_kinds else None
        image_path = out_root / entry["image"]

        try:
            image_urls = [client.upload_image(image_path)] if image_path.exists() else []
            data = client.publish(body.strip(), images=image_urls, title=title)
        except publisher.PublishError as exc:
            print(f"  ✗ {kind:<14} {exc}", file=sys.stderr)
            results.append(publisher.PublishResult(slug, kind, "failed", error=str(exc)))
            continue

        if dry_run:
            print(f"  ○ {kind:<14} 乾跑通過　contentType={data['body']['contentType']}"
                  f"　{len(body.strip())} 字")
            results.append(publisher.PublishResult(slug, kind, "skipped"))
            continue

        content_id = str(data.get("id") or data.get("contentId") or "") or None
        url = f"https://www.binance.com/zh-TC/square/post/{content_id}" if content_id else None
        ledger.record(cfg, book, day_str, slug, kind=kind, content_id=content_id, url=url)
        print(f"  ✓ {kind:<14} 已發布" + (f"　{url}" if url else "　(未回傳 id)"))
        results.append(publisher.PublishResult(slug, kind, "published", content_id, url))

    published = [r for r in results if r.status == "published"]
    failed = [r for r in results if r.status == "failed"]
    print(f"\n發布 {len(published)} 篇、跳過 {len(results) - len(published) - len(failed)} 篇、"
          f"失敗 {len(failed)} 篇。今日累計 {ledger.count_on(book, day_str)} 篇。")

    if published and not dry_run:
        tracker.append(cfg, tracker.Entry(
            date=day_str, posts_published=len(published), notes="由排程自動發布"
        ))
    return 1 if failed else 0


def cmd_publish(args, cfg) -> int:
    day = dt.date.fromisoformat(args.date) if args.date else cfg.now().date()
    kinds = [args.kind] if args.kind else None
    return _publish_day(cfg, day, kinds=kinds, dry_run=args.dry_run)


def cmd_preview(args, cfg) -> int:
    snap = _snapshot(cfg, args.offline)
    kinds = [args.kind] if args.kind else compose.kinds_for(snap.generated_at.date())
    for kind in kinds:
        post = compose.build(kind, cfg, snap)
        print("=" * 60)
        print(f"[{kind}] {post.title}")
        print("=" * 60)
        print(post.to_markdown(cfg))
    return 0


def cmd_track(args, cfg) -> int:
    entry = tracker.Entry(
        date=args.date or "",
        followers=args.followers or 0,
        posts_published=args.posts or 0,
        impressions=args.impressions or 0,
        profile_clicks=args.clicks or 0,
        referral_signups=args.signups or 0,
        referral_volume_usdt=args.volume or 0.0,
        commission_usdt=args.commission or 0.0,
        notes=args.notes or "",
    )
    p = tracker.append(cfg, entry)
    print(f"已寫入 {p}")
    print()
    print(tracker.status(cfg))
    return 0


def cmd_status(args, cfg) -> int:
    print(tracker.status(cfg))
    return 0


def cmd_topics(args, cfg) -> int:
    today = cfg.now().date()
    current = compose.education_index(today)
    print(f"教育課綱共 {len(topics.TOPICS)} 篇，一週三篇約可撐 {topics.coverage_weeks():.0f} 週不重複。")
    slot = current % len(topics.TOPICS)
    cycle = current // len(topics.TOPICS) + 1
    print(f"今天（{today}）的輪替位置：第 {slot + 1} 篇（第 {cycle} 輪）\n")
    for i, t in enumerate(topics.TOPICS):
        marker = "→" if i == slot else " "
        print(f"{marker} {i + 1:>2}. [{t.track}] {t.title}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="square", description="幣安廣場內容生產線")
    p.add_argument("--config", type=Path, default=None)
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="產生貼文草稿與配圖")
    g.add_argument("--kind", choices=list(compose.BUILDERS))
    g.add_argument("--offline", action="store_true", help="不連網，用示意資料測版面")
    g.add_argument("--publish", action="store_true", help="產生後直接發布")
    g.add_argument("--dry-run", action="store_true", help="配合 --publish：只印不送")
    g.set_defaults(func=cmd_generate)

    pub = sub.add_parser("publish", help="發布 out/ 裡尚未發過的貼文")
    pub.add_argument("--date", help="預設今天，格式 YYYY-MM-DD")
    pub.add_argument("--kind", choices=list(compose.BUILDERS))
    pub.add_argument("--dry-run", action="store_true", help="只印出將送出的內容，不真的發")
    pub.set_defaults(func=cmd_publish)

    v = sub.add_parser("preview", help="只印文案不存檔")
    v.add_argument("--kind", choices=list(compose.BUILDERS))
    v.add_argument("--offline", action="store_true")
    v.set_defaults(func=cmd_preview)

    t = sub.add_parser("track", help="記錄一筆成長數據")
    t.add_argument("--date")
    t.add_argument("--followers", type=int)
    t.add_argument("--posts", type=int)
    t.add_argument("--impressions", type=int)
    t.add_argument("--clicks", type=int)
    t.add_argument("--signups", type=int)
    t.add_argument("--volume", type=float)
    t.add_argument("--commission", type=float)
    t.add_argument("--notes")
    t.set_defaults(func=cmd_track)

    s = sub.add_parser("status", help="目標進度與漏斗診斷")
    s.set_defaults(func=cmd_status)

    c = sub.add_parser("topics", help="列出教育課綱")
    c.set_defaults(func=cmd_topics)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load(args.config)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
