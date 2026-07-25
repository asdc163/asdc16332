"""貼文文案生成。

四種貼文型別：
  morning_brief 早報   — 每日，真實行情數據 + 當日觀察重點
  education     教育   — 週一三五，topics.py 的課綱輪替
  data_watch    數據   — 週二四六，漲跌幅榜／資金費率／情緒指標
  weekly        週報   — 週日，一週回顧

所有文案只描述已發生的市場數據與機制知識，不預測價格、不給進出場建議。
產出是 Markdown 草稿，附 YAML front matter 方便你審閱與追蹤。
"""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass

from . import topics as topic_lib
from .market import Snapshot, Ticker

# 教育系列輪替的起算日（系列第 1 篇的日期）。
# 改這個會打亂已發過的順序，上線後不要再動。
EDU_EPOCH = dt.date(2026, 7, 27)
EDU_WEEKDAYS = {0, 2, 4}  # 週一、三、五

WEEKDAY_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


@dataclass
class Post:
    kind: str
    title: str
    body: str
    hashtags: list[str]
    image_spec: dict
    slug: str

    def to_markdown(self, cfg) -> str:
        disclaimer = cfg.get("content", "disclaimer", default="")
        ref_kinds = cfg.get("brand", "referral_on", default=[])
        parts = [self.body.strip(), ""]
        if disclaimer:
            parts += [disclaimer, ""]
        if self.kind in ref_kinds:
            url = cfg.get("brand", "referral_url")
            if url:
                parts += [f"想一起研究的話，我的幣安連結在這：{url}", ""]
        parts.append(" ".join(self.hashtags))
        return "\n".join(parts).strip() + "\n"


# ---------------------------------------------------------------- 格式化工具

def fmt_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:,.2f}"
    if value >= 0.01:
        return f"{value:.4f}"
    return f"{value:.6f}"


def fmt_pct(value: float, sign: bool = True) -> str:
    prefix = "+" if sign and value > 0 else ""
    return f"{prefix}{value:.2f}%"


def fmt_volume(value: float) -> str:
    if value >= 1e9:
        return f"{value / 1e9:.1f}B"
    if value >= 1e6:
        return f"{value / 1e6:.0f}M"
    return f"{value:,.0f}"


def arrow(value: float) -> str:
    return "▲" if value > 0 else "▼" if value < 0 else "—"


def education_index(day: dt.date) -> int:
    """這一天是第幾篇教育貼文（只計算週一三五）。"""
    count = 0
    cursor = EDU_EPOCH
    while cursor < day:
        if cursor.weekday() in EDU_WEEKDAYS:
            count += 1
        cursor += dt.timedelta(days=1)
    return count


def _rng(day: dt.date, salt: str) -> random.Random:
    return random.Random(f"{day.isoformat()}-{salt}")


def _pick_tags(base: list[str], cfg, day: dt.date, salt: str) -> list[str]:
    n = cfg.get("content", "hashtags_per_post", default=3)
    rng = _rng(day, salt)
    pool = list(dict.fromkeys(base))
    rng.shuffle(pool)
    return pool[:n]


# ---------------------------------------------------------------- 早報

_OPENERS = [
    "早安，先看一眼昨天發生了什麼。",
    "開盤前的例行掃描，數據先擺出來。",
    "昨天的市場動態整理，一分鐘看完。",
    "每日行情快報，只講數字不講故事。",
]


def morning_brief(cfg, snap: Snapshot) -> Post:
    day = snap.generated_at.date()
    rng = _rng(day, "morning")
    lines = [rng.choice(_OPENERS), ""]

    for sym, t in snap.tickers.items():
        pos = t.range_position
        where = "接近區間高點" if pos > 0.75 else "接近區間低點" if pos < 0.25 else "在區間中段"
        lines.append(
            f"{arrow(t.change_pct)} {t.base} ${fmt_price(t.last)}（24h {fmt_pct(t.change_pct)}）"
            f"　高 {fmt_price(t.high)} / 低 {fmt_price(t.low)}，目前{where}。"
        )

    up, down = snap.breadth
    lines += ["", f"觀察名單 {up} 漲 {down} 跌。"]

    if snap.fear_greed:
        value, label = snap.fear_greed
        lines.append(f"恐懼貪婪指數 {value}（{label}）。")

    lead = max(snap.tickers.values(), key=lambda t: abs(t.change_pct), default=None)
    if lead:
        lines += [
            "",
            f"波動最大的是 {lead.base}，24 小時走了 {abs(lead.change_pct):.2f}%，"
            f"成交額 {fmt_volume(lead.quote_volume)} USDT。"
            "幅度大的時候，先確認自己的部位在極端行情下撐不撐得住，再想方向。",
        ]

    tags = _pick_tags(
        ["#每日行情", "#BTC", "#ETH", "#加密貨幣", "#市場觀察", "#幣安廣場"], cfg, day, "morning"
    )
    return Post(
        kind="morning_brief",
        title=f"{day.strftime('%m/%d')} 早報：{lead.base if lead else 'BTC'} 領動",
        body="\n".join(lines),
        hashtags=tags,
        image_spec={"type": "market_card", "symbols": list(snap.tickers.keys())},
        slug="morning-brief",
    )


# ---------------------------------------------------------------- 教育

def education(cfg, snap: Snapshot, index: int | None = None) -> Post:
    day = snap.generated_at.date()
    idx = education_index(day) if index is None else index
    topic = topic_lib.pick(idx)

    lines = [topic.hook, ""]
    for i, (head, detail) in enumerate(topic.points, 1):
        lines.append(f"{i}. {head}")
        lines.append(f"　　{detail}")
        lines.append("")
    lines += [topic.takeaway, "", topic.question]

    tags = _pick_tags(topic.tags + ["#幣安廣場", "#加密教學"], cfg, day, f"edu-{topic.id}")
    return Post(
        kind="education",
        title=topic.title,
        body="\n".join(lines),
        hashtags=tags,
        image_spec={
            "type": "education_poster",
            "title": topic.title,
            "track": topic.track,
            "points": [head for head, _ in topic.points],
            "takeaway": topic.takeaway,
            "index": idx % len(topic_lib.TOPICS) + 1,
        },
        slug=f"education-{topic.id}",
    )


# ---------------------------------------------------------------- 數據觀察

def data_watch(cfg, snap: Snapshot) -> Post:
    day = snap.generated_at.date()
    lines = ["今天不看價格，看資料。", ""]

    if snap.gainers:
        lines.append("24 小時漲幅前段（已濾掉低流動性標的）：")
        for t in snap.gainers:
            lines.append(f"　{t.base} {fmt_pct(t.change_pct)}　成交額 {fmt_volume(t.quote_volume)}")
        lines.append("")

    if snap.losers:
        lines.append("跌幅前段：")
        for t in snap.losers:
            lines.append(f"　{t.base} {fmt_pct(t.change_pct)}　成交額 {fmt_volume(t.quote_volume)}")
        lines.append("")

    if snap.funding:
        lines.append("永續資金費率（正＝多方付費給空方，代表槓桿偏多）：")
        for sym, rate in snap.funding.items():
            lines.append(f"　{sym.removesuffix('USDT')} {rate:+.4f}%")
        crowded = [s for s, r in snap.funding.items() if abs(r) > 0.02]
        if crowded:
            names = "、".join(s.removesuffix("USDT") for s in crowded)
            lines.append(f"　{names} 的費率偏離中性，代表這幾檔的槓桿比較擁擠。")
        lines.append("")

    if snap.fear_greed:
        value, label = snap.fear_greed
        lines += [f"市場情緒：恐懼貪婪指數 {value}（{label}）。", ""]

    lines.append(
        "提醒一句：漲幅榜是結果不是入場理由，榜上的標的通常也是滑價最大的標的。"
        "看榜單的用途是知道資金往哪流，不是照著買。"
    )

    tags = _pick_tags(
        ["#漲幅榜", "#資金費率", "#市場數據", "#加密貨幣", "#鏈上數據", "#幣安廣場"],
        cfg, day, "watch",
    )
    return Post(
        kind="data_watch",
        title=f"{day.strftime('%m/%d')} 數據觀察：漲跌幅與資金費率",
        body="\n".join(lines),
        hashtags=tags,
        image_spec={"type": "leaderboard", "gainers": snap.gainers, "losers": snap.losers},
        slug="data-watch",
    )


# ---------------------------------------------------------------- 週報

def weekly_review(cfg, snap: Snapshot, history: list[dict] | None = None) -> Post:
    day = snap.generated_at.date()
    monday = day - dt.timedelta(days=day.weekday())
    lines = [
        f"{monday.strftime('%m/%d')}–{day.strftime('%m/%d')} 這一週的整理。",
        "",
        "主要標的週間表現：",
    ]

    for sym, t in snap.tickers.items():
        lines.append(
            f"　{arrow(t.change_pct)} {t.base} ${fmt_price(t.last)}"
            f"　區間 {fmt_price(t.low)}–{fmt_price(t.high)}"
        )

    up, down = snap.breadth
    lines += ["", f"觀察名單收在 {up} 漲 {down} 跌。"]

    if snap.fear_greed:
        value, label = snap.fear_greed
        lines.append(f"情緒面收在 {value}（{label}）。")

    idx = education_index(day)
    recent = [topic_lib.pick(i) for i in range(max(0, idx - 3), idx)]
    if recent:
        lines += ["", "這週聊過的主題："]
        for t in recent:
            lines.append(f"　・{t.title}")

    lines += [
        "",
        "下週我會繼續每天早上發行情快報、一三五發教育系列、二四六發數據觀察。"
        "有想看的主題留言告訴我，我排進課綱。",
    ]

    tags = _pick_tags(
        ["#週報", "#市場回顧", "#加密貨幣", "#投資筆記", "#幣安廣場"], cfg, day, "weekly"
    )
    return Post(
        kind="weekly",
        title=f"週報 {monday.strftime('%m/%d')}–{day.strftime('%m/%d')}",
        body="\n".join(lines),
        hashtags=tags,
        image_spec={"type": "weekly_card", "symbols": list(snap.tickers.keys())},
        slug="weekly-review",
    )


# ---------------------------------------------------------------- 排程決策

def kinds_for(day: dt.date) -> list[str]:
    """這一天該產出哪些貼文。"""
    kinds = ["morning_brief"]
    if day.weekday() in EDU_WEEKDAYS:
        kinds.append("education")
    if day.weekday() in {1, 3, 5}:
        kinds.append("data_watch")
    if day.weekday() == 6:
        kinds.append("weekly")
    return kinds


BUILDERS = {
    "morning_brief": morning_brief,
    "education": education,
    "data_watch": data_watch,
    "weekly": weekly_review,
}


def build(kind: str, cfg, snap: Snapshot) -> Post:
    if kind not in BUILDERS:
        raise ValueError(f"未知的貼文型別: {kind}")
    return BUILDERS[kind](cfg, snap)
