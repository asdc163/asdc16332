"""每週績效檢視與策略調整建議。

這是專案經理那一層：管線負責產出與發布，這裡負責回答「有沒有效、下一步改什麼」。

資料來源分兩種，性質完全不同：
  發布健康度  來自 data/published.json，完全自動，不需要人工輸入
  成長數據    來自 data/tracking.csv，廣場沒有統計 API，只能人工抄

所以檢視報告會把兩者分開講：發布健康度是事實，成長數據缺了就明說缺了，
不會拿沒有的數字硬湊結論。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import compose, ledger, topics, tracker


@dataclass
class WeekWindow:
    start: dt.date
    end: dt.date

    @property
    def days(self) -> list[dt.date]:
        span = (self.end - self.start).days
        return [self.start + dt.timedelta(days=i) for i in range(span + 1)]

    def contains(self, day: dt.date) -> bool:
        return self.start <= day <= self.end

    def __str__(self) -> str:
        return f"{self.start.strftime('%m/%d')}–{self.end.strftime('%m/%d')}"


def week_ending(day: dt.date) -> WeekWindow:
    """含 day 在內的最近 7 天。"""
    return WeekWindow(day - dt.timedelta(days=6), day)


@dataclass
class PublishHealth:
    expected: int = 0
    actual: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.actual / self.expected if self.expected else 0.0

    @property
    def healthy(self) -> bool:
        return self.expected > 0 and self.rate >= 0.9


def publish_health(cfg, window: WeekWindow) -> PublishHealth:
    book = ledger.load(cfg)
    health = PublishHealth()
    live_since = _live_since(cfg)
    for day in window.days:
        # 上線之前的日子不算漏發，否則第一週的報告會被一堆假警報淹掉
        if live_since and day < live_since:
            continue
        day_str = day.isoformat()
        for kind in compose.kinds_for(day):
            health.expected += 1
            slug = _slug_for(kind, day)
            if slug and ledger.is_published(book, day_str, slug):
                health.actual += 1
            else:
                health.missing.append(f"{day.strftime('%m/%d')} {kind}")
    return health


def _live_since(cfg) -> dt.date | None:
    raw = cfg.get("publish", "live_since", default=None)
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        return None


def _slug_for(kind: str, day: dt.date) -> str | None:
    """重建當天該型別的 slug，用來對帳。教育貼文的 slug 帶主題 id。"""
    if kind == "education":
        idx = compose.education_index(day)
        return f"education-{topics.pick(idx).id}"
    return {
        "morning_brief": "morning-brief",
        "data_watch": "data-watch",
        "weekly": "weekly-review",
    }.get(kind)


@dataclass
class Funnel:
    posts: int = 0
    impressions: int = 0
    clicks: int = 0
    signups: int = 0
    commission: float = 0.0
    followers_start: int = 0
    followers_end: int = 0
    has_data: bool = False

    @property
    def follower_delta(self) -> int:
        return self.followers_end - self.followers_start

    @property
    def click_rate(self) -> float | None:
        return self.clicks / self.impressions if self.impressions else None

    @property
    def signup_rate(self) -> float | None:
        return self.signups / self.clicks if self.clicks else None

    @property
    def impressions_per_post(self) -> float | None:
        return self.impressions / self.posts if self.posts else None


def funnel_for(cfg, window: WeekWindow) -> Funnel:
    inside: list[tracker.Entry] = []
    before: list[tracker.Entry] = []
    for entry in tracker.read(cfg):
        try:
            day = dt.date.fromisoformat(entry.date)
        except ValueError:
            continue
        if window.contains(day):
            inside.append(entry)
        elif day < window.start:
            before.append(entry)
        # 視窗之後的紀錄（例如手動補未來日期）不列入本週統計

    f = Funnel()
    f.impressions = sum(e.impressions for e in inside)
    f.clicks = sum(e.profile_clicks for e in inside)
    f.signups = sum(e.referral_signups for e in inside)
    f.commission = sum(e.commission_usdt for e in inside)
    f.posts = sum(e.posts_published for e in inside)

    followers = [e.followers for e in inside if e.followers > 0]
    f.followers_end = followers[-1] if followers else 0
    prior = [e.followers for e in before if e.followers > 0]
    f.followers_start = prior[-1] if prior else (followers[0] if followers else 0)
    f.has_data = bool(f.impressions or f.followers_end)
    return f


# ---------------------------------------------------------------- 建議

def recommendations(cfg, health: PublishHealth, funnel: Funnel) -> list[str]:
    """依數據給具體動作。每一條都要能直接執行，不要講「多多互動」這種廢話。"""
    goal_rev = cfg.get("goals", "weekly_revenue_usdt", default=200)
    goal_fans = cfg.get("goals", "followers", default=10000)
    out: list[str] = []

    if not health.healthy and health.expected:
        out.append(
            f"**先修管線。** 本週應發 {health.expected} 篇、實際 {health.actual} 篇。"
            f"漏掉的：{'、'.join(health.missing[:5])}"
            f"{' 等' if len(health.missing) > 5 else ''}。"
            "到 Actions 看失敗的執行紀錄，通常是金鑰過期（220004）或達每日上限（220009）。"
            "內容再好，沒發出去都是零。"
        )

    if not funnel.has_data:
        out.append(
            "**缺成長數據，無法診斷。** 廣場沒有統計 API，粉絲數與曝光只能人工抄。"
            "在本週的檢視 issue 直接回覆五個數字即可，會自動寫進 tracking.csv。"
            "沒有這些數字，下面所有的優化都只能用猜的。"
        )
        return out

    ipp = funnel.impressions_per_post
    if ipp is not None and ipp < 300:
        out.append(
            f"**觸及是目前的瓶頸**（每篇平均曝光 {ipp:.0f}）。優先做三件事："
            "貼文帶當週熱門話題標籤而不是固定標籤；"
            "在流量大的貼文底下留有實質內容的長留言（不是「同意」這種）；"
            "確認發文時間沒有飄——演算法吃穩定性。"
        )
    elif funnel.click_rate is not None and funnel.click_rate < 0.01:
        out.append(
            f"**有人看完但不點進個人頁**（曝光→點擊 {funnel.click_rate * 100:.2f}%，健康值約 1–3%）。"
            "問題在鉤子不在觸及：貼文結尾改成明確的續集預告（「明天講 X」），"
            "個人簡介寫清楚你固定發什麼、什麼時間發。"
        )
    elif funnel.signups == 0 and funnel.clicks > 50:
        out.append(
            f"**{funnel.clicks} 次進個人頁、0 註冊。** 動線斷了。"
            "檢查推薦連結有沒有出現在個人簡介與置頂貼文，"
            "而不是只埋在單篇貼文的結尾。"
        )
    elif funnel.signup_rate is not None and funnel.signup_rate < 0.02:
        out.append(
            f"**點擊到註冊轉換偏低**（{funnel.signup_rate * 100:.2f}%，健康值約 2–5%）。"
            "CTA 太模糊。與其放連結，不如給一個具體的註冊理由，"
            "並考慮縮減附連結的貼文比例，避免整個帳號被讀成推廣號。"
        )

    if funnel.commission < goal_rev * 0.5 and funnel.signups > 0:
        out.append(
            f"**漏斗前段成立，返佣還沒跟上**（本週 {funnel.commission:.2f} / {goal_rev} USDT）。"
            "返佣落後於註冊是正常的——它取決於推薦人開始交易的時間與量。"
            "這一階段不要改內容策略，把資源放在把漏斗頂端做寬。"
        )

    delta = funnel.follower_delta
    if delta > 0:
        remaining = max(0, goal_fans - funnel.followers_end)
        weeks = remaining / delta
        if weeks > 52:
            out.append(
                f"**目前增速下破萬需要 {weeks:.0f} 週**（本週 +{delta}）。"
                "這個速度靠自然增長到不了。要嘛提高發文以外的曝光管道（留言、互動、跨平台導流），"
                "要嘛把破萬粉這個目標改成階段性目標，先設 1000。"
            )
        else:
            out.append(f"**照目前增速約 {weeks:.0f} 週破萬**（本週 +{delta}）。維持節奏。")
    elif funnel.has_data:
        out.append(
            f"**本週粉絲沒有淨增長**（{delta:+d}）。內容有出去但沒有轉化成追蹤，"
            "代表題材對讀者不夠有用。下週把教育系列的比重拉高，行情快報壓低。"
        )

    if not out:
        out.append("各層數據都在合理範圍，維持現在的節奏，不需要調整。")
    return out


# ---------------------------------------------------------------- 報告

def _pct(value: float | None) -> str:
    return f"{value * 100:.2f}%" if value is not None else "—"


def build_report(cfg, day: dt.date | None = None) -> str:
    day = day or cfg.now().date()
    window = week_ending(day)
    health = publish_health(cfg, window)
    funnel = funnel_for(cfg, window)
    goal_rev = cfg.get("goals", "weekly_revenue_usdt", default=200)
    goal_fans = cfg.get("goals", "followers", default=10000)

    lines = [f"# 每週檢視 {window}", "", "## 發布健康度", ""]
    if health.expected == 0:
        lines.append("這一週還沒進入排程範圍（尚未上線），沒有發布紀錄可以對帳。")
    else:
        icon = "✅" if health.healthy else "⚠️"
        lines.append(
            f"{icon} 應發 **{health.expected}** 篇，實際發出 **{health.actual}** 篇"
            f"（{health.rate * 100:.0f}%）"
        )
    if health.missing:
        lines += ["", "漏發："]
        lines += [f"- {m}" for m in health.missing[:10]]
        if len(health.missing) > 10:
            lines.append(f"- …另外還有 {len(health.missing) - 10} 篇")

    lines += ["", "## 成長漏斗", ""]
    if funnel.has_data:
        lines += [
            "| 層級 | 本週 | 轉換率 |",
            "|---|---:|---:|",
            f"| 曝光 | {funnel.impressions:,} | — |",
            f"| 進個人頁 | {funnel.clicks:,} | {_pct(funnel.click_rate)} |",
            f"| 推薦註冊 | {funnel.signups:,} | {_pct(funnel.signup_rate)} |",
            f"| 返佣 | {funnel.commission:.2f} USDT | — |",
            "",
            f"粉絲數 **{funnel.followers_end:,}** / {goal_fans:,}"
            f"（本週 {funnel.follower_delta:+,}）",
            f"本週收益 **{funnel.commission:.2f}** / {goal_rev} USDT"
            f"（{funnel.commission / goal_rev * 100:.0f}%）",
        ]
    else:
        lines += [
            "本週沒有成長數據。廣場沒有開放統計 API，這幾個數字只能從後台人工抄。",
            "",
            "**直接回覆這則 issue，貼上以下五行即可（會自動寫進 `data/tracking.csv`）：**",
            "",
            "```",
            "followers: ",
            "impressions: ",
            "clicks: ",
            "signups: ",
            "commission: ",
            "```",
        ]

    lines += ["", "## 下一步", ""]
    for i, rec in enumerate(recommendations(cfg, health, funnel), 1):
        lines.append(f"{i}. {rec}")

    idx = compose.education_index(day)
    upcoming = [topics.pick(i) for i in range(idx, idx + 3)]
    lines += ["", "## 下週教育系列排程", ""]
    lines += [f"- [{t.track}] {t.title}" for t in upcoming]

    return "\n".join(lines) + "\n"
