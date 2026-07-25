"""指令列進入點。

  python -m square generate            產生今天該發的所有貼文草稿與配圖
  python -m square generate --kind education --offline
  python -m square preview             只印文案不存檔
  python -m square track --followers 1234 --commission 18.5
  python -m square status              看目標進度與漏斗診斷
  python -m square topics              列出教育課綱與輪替順序
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import compose, config, imagegen, market, topics, tracker


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
    print("請先審閱再手動發布到幣安廣場。")
    return 0


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
    g.set_defaults(func=cmd_generate)

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
