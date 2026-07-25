"""從自由文字裡抽出成長數據。

廣場沒有開放統計 API，粉絲數與曝光只能人工抄。與其要求跑指令，
不如讓你直接在每週檢視 issue 底下回一則留言，這個模組負責解析。

接受寬鬆的寫法，中英文皆可，順序不拘：

    followers: 1250
    曝光 8,400
    clicks=96
    註冊 4
    佣金 23.5 USDT

沒提到的欄位就是 0，不會拿舊值去猜。
"""
from __future__ import annotations

import re

# 每個欄位的別名。比對時全部轉小寫，中文不受影響。
ALIASES: dict[str, list[str]] = {
    "followers": ["followers", "follower", "粉絲數", "粉絲", "追蹤數", "追蹤者"],
    "impressions": ["impressions", "impression", "views", "曝光數", "曝光", "瀏覽數", "觀看"],
    "profile_clicks": ["clicks", "click", "profile_clicks", "點擊數", "點擊", "進個人頁", "個人頁"],
    "referral_signups": ["signups", "signup", "referrals", "註冊數", "註冊", "推薦註冊", "邀請人數"],
    "commission_usdt": ["commission", "revenue", "返佣", "佣金", "收益", "收入"],
    "referral_volume_usdt": ["volume", "交易量", "成交量"],
}

FLOAT_FIELDS = {"commission_usdt", "referral_volume_usdt"}

# 別名後面允許冒號、等號、全形冒號或純空白，接著一個數字（可帶千分位與小數）
_NUMBER = r"[-+]?[\d,]*\.?\d+"


def _pattern(alias: str) -> re.Pattern:
    return re.compile(
        rf"{re.escape(alias)}\s*[:：=]?\s*({_NUMBER})",
        re.IGNORECASE,
    )


def parse(text: str) -> dict[str, float]:
    """回傳有找到的欄位。找不到的欄位不會出現在結果裡。"""
    found: dict[str, float] = {}
    for field, aliases in ALIASES.items():
        # 長別名優先，避免「粉絲」先吃掉「粉絲數」的比對位置
        for alias in sorted(aliases, key=len, reverse=True):
            match = _pattern(alias).search(text)
            if not match:
                continue
            raw = match.group(1).replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            if value < 0:
                continue
            found[field] = value if field in FLOAT_FIELDS else int(value)
            break
    return found


def to_entry(cfg, text: str, date: str | None = None):
    """解析後轉成追蹤表的一列。沒有任何欄位命中就回 None。"""
    from . import tracker

    values = parse(text)
    if not values:
        return None
    entry = tracker.Entry(date=date or cfg.now().date().isoformat(), notes="由檢視 issue 回報")
    for field, value in values.items():
        setattr(entry, field, value)
    return entry


def summarise(values: dict[str, float]) -> str:
    if not values:
        return "沒有解析到任何數字。"
    labels = {
        "followers": "粉絲數",
        "impressions": "曝光",
        "profile_clicks": "進個人頁",
        "referral_signups": "推薦註冊",
        "commission_usdt": "返佣",
        "referral_volume_usdt": "交易量",
    }
    parts = [
        f"{labels.get(k, k)} {v:,.2f}".rstrip("0").rstrip(".") if k in FLOAT_FIELDS
        else f"{labels.get(k, k)} {v:,.0f}"
        for k, v in values.items()
    ]
    return "已記錄：" + "、".join(parts)
