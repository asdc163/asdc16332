"""成長與收益追蹤。

「每週 200U + 破萬粉」是漏斗問題，不是發文問題：
    曝光 → 進個人頁 → 點推薦連結 → 註冊 → 入金交易 → 返佣

只記錄粉絲數不會知道卡在哪一層。這張表把每一層都記下來，
每週用 `status` 看轉換率，才知道下一步該改內容還是改 CTA。
數字要你自己從幣安廣場後台與推薦儀表板抄過來，沒有 API 能自動抓。
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import iso_week

FILENAME = "tracking.csv"


@dataclass
class Entry:
    date: str = ""
    iso_week: str = ""
    followers: int = 0
    posts_published: int = 0
    impressions: int = 0
    profile_clicks: int = 0
    referral_signups: int = 0
    referral_volume_usdt: float = 0.0
    commission_usdt: float = 0.0
    notes: str = ""


COLUMNS = [f.name for f in fields(Entry)]

# 明確指定每欄的轉型器。不要用 dataclasses.fields 的 .type：
# 這個模組有 `from __future__ import annotations`，型別註記是字串不是型別物件。
CONVERTERS = {
    "date": str,
    "iso_week": str,
    "notes": str,
    "followers": int,
    "posts_published": int,
    "impressions": int,
    "profile_clicks": int,
    "referral_signups": int,
    "referral_volume_usdt": float,
    "commission_usdt": float,
}


def path_for(cfg) -> Path:
    return cfg.data_dir / FILENAME


def ensure(cfg) -> Path:
    p = path_for(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        with open(p, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
    return p


def read(cfg) -> list[Entry]:
    p = ensure(cfg)
    out: list[Entry] = []
    with open(p, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            entry = Entry()
            for col in COLUMNS:
                raw = (row.get(col) or "").strip()
                conv = CONVERTERS[col]
                if conv is str:
                    setattr(entry, col, raw)
                    continue
                try:
                    setattr(entry, col, conv(float(raw or 0)))
                except ValueError:
                    setattr(entry, col, conv(0))
            out.append(entry)
    return sorted(out, key=lambda e: e.date)


def append(cfg, entry: Entry) -> Path:
    p = ensure(cfg)
    if not entry.date:
        entry.date = cfg.now().date().isoformat()
    if not entry.iso_week:
        entry.iso_week = iso_week(dt.date.fromisoformat(entry.date))
    with open(p, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=COLUMNS).writerow(asdict(entry))
    return p


def _pct(numer: float, denom: float) -> str:
    return f"{numer / denom * 100:.2f}%" if denom else "—"


def status(cfg) -> str:
    entries = read(cfg)
    goal_rev = cfg.get("goals", "weekly_revenue_usdt", default=200)
    goal_fans = cfg.get("goals", "followers", default=10000)

    if not entries:
        return (
            "追蹤表還是空的。\n"
            f"先跑一次：python -m square track --followers <目前粉絲數>\n"
            f"目標：每週 {goal_rev} USDT、粉絲 {goal_fans}。"
        )

    latest = entries[-1]
    today = cfg.now().date()
    week_ago = today - dt.timedelta(days=7)
    recent = [e for e in entries if dt.date.fromisoformat(e.date) >= week_ago]

    week_commission = sum(e.commission_usdt for e in recent)
    week_posts = sum(e.posts_published for e in recent)
    week_impr = sum(e.impressions for e in recent)
    week_clicks = sum(e.profile_clicks for e in recent)
    week_signups = sum(e.referral_signups for e in recent)

    prior = [e for e in entries if dt.date.fromisoformat(e.date) < week_ago]
    fan_delta = latest.followers - prior[-1].followers if prior else 0

    remaining = max(0, goal_fans - latest.followers)
    weeks_needed = f"{remaining / fan_delta:.0f} 週" if fan_delta > 0 else "以目前增速無法估算"

    lines = [
        f"== 進度（截至 {latest.date}）==",
        "",
        f"粉絲數　　{latest.followers:,} / {goal_fans:,}"
        f"　({latest.followers / goal_fans * 100:.1f}%)　近 7 日 {fan_delta:+,}",
        f"到達目標　{weeks_needed}",
        "",
        f"本週收益　{week_commission:.2f} / {goal_rev} USDT"
        f"　({week_commission / goal_rev * 100:.0f}%)",
        "",
        "== 近 7 日漏斗 ==",
        f"發文　　　{week_posts}",
        f"曝光　　　{week_impr:,}",
        f"進個人頁　{week_clicks:,}　(曝光→點擊 {_pct(week_clicks, week_impr)})",
        f"推薦註冊　{week_signups:,}　(點擊→註冊 {_pct(week_signups, week_clicks)})",
        f"返佣　　　{week_commission:.2f} USDT"
        + (f"　(每註冊 {week_commission / week_signups:.2f} USDT)" if week_signups else ""),
        "",
        _diagnose(week_impr, week_clicks, week_signups, week_commission, week_posts, goal_rev),
    ]
    return "\n".join(lines)


def _diagnose(impr, clicks, signups, commission, posts, goal_rev) -> str:
    """指出漏斗最弱的一環，避免只看總數卻不知道該改什麼。"""
    if posts == 0:
        return "診斷：這週沒有發文紀錄。先把發文頻率穩定下來，其他都是後話。"
    if impr == 0:
        return "診斷：沒有曝光數據。到廣場後台把數字抄進來，不然無法判斷問題在哪一層。"
    if impr < 3000:
        return (
            "診斷：曝光太低，問題在觸及不在轉換。優先做：貼文帶熱門話題標籤、"
            "在別人的熱門貼文下留有內容的長留言、發文時間固定。"
        )
    if clicks / impr < 0.01:
        return (
            "診斷：有曝光但很少人點進個人頁。內容被看完了卻沒有讓人想追蹤——"
            "試著讓貼文結尾留一個明確的續集鉤子，並確認個人簡介寫清楚你固定發什麼。"
        )
    if signups == 0:
        return (
            "診斷：有人進個人頁但沒有推薦註冊。檢查推薦連結是否真的出現在動線上"
            "（個人簡介、置頂貼文），以及有沒有給出註冊的具體理由。"
        )
    if clicks and signups / clicks < 0.02:
        return "診斷：點擊到註冊的轉換偏低。CTA 太模糊或出現得太突兀，考慮只在教育／週報貼文附連結。"
    if commission < goal_rev * 0.5:
        return (
            "診斷：漏斗前段健康，但返佣不足。返佣取決於推薦人的交易量，"
            "累積需要時間；同時間把重心放在擴大曝光，讓漏斗頂端變寬。"
        )
    return "診斷：各層轉換都在合理範圍，維持現在的節奏並持續擴大曝光。"
