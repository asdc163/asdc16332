"""幣安公開行情資料抓取。

只使用不需要 API key 的公開端點：
  - https://api.binance.com/api/v3/ticker/24hr   24 小時漲跌統計
  - https://api.binance.com/api/v3/klines        K 線（畫走勢用）
  - https://fapi.binance.com/fapi/v1/premiumIndex 永續資金費率
  - https://api.alternative.me/fng/              恐懼貪婪指數（第三方，失敗就略過）

離線模式 (offline=True) 產生以日期為種子的假資料，供無網路環境測試版面。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SPOT = "https://api.binance.com/api/v3"
FUTURES = "https://fapi.binance.com/fapi/v1"
FNG = "https://api.alternative.me/fng/?limit=1"

_UA = {"User-Agent": "square-content-pipeline/1.0"}


class MarketError(RuntimeError):
    pass


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarketError(f"{url} 取得失敗: {exc}") from exc


@dataclass
class Ticker:
    symbol: str
    last: float
    change_pct: float
    high: float
    low: float
    quote_volume: float

    @property
    def base(self) -> str:
        return self.symbol.removesuffix("USDT")

    @property
    def range_position(self) -> float:
        """收盤價位於 24h 高低區間的哪個位置，0=貼近低點，1=貼近高點。"""
        span = self.high - self.low
        return 0.5 if span <= 0 else max(0.0, min(1.0, (self.last - self.low) / span))


@dataclass
class Snapshot:
    generated_at: dt.datetime
    tickers: dict[str, Ticker] = field(default_factory=dict)
    sparklines: dict[str, list[float]] = field(default_factory=dict)
    gainers: list[Ticker] = field(default_factory=list)
    losers: list[Ticker] = field(default_factory=list)
    funding: dict[str, float] = field(default_factory=dict)
    fear_greed: tuple[int, str] | None = None
    offline: bool = False

    def get(self, symbol: str) -> Ticker | None:
        return self.tickers.get(symbol)

    @property
    def breadth(self) -> tuple[int, int]:
        """觀察名單中上漲 / 下跌的檔數。"""
        up = sum(1 for t in self.tickers.values() if t.change_pct > 0)
        return up, len(self.tickers) - up


def _parse_ticker(row: dict) -> Ticker:
    return Ticker(
        symbol=row["symbol"],
        last=float(row["lastPrice"]),
        change_pct=float(row["priceChangePercent"]),
        high=float(row["highPrice"]),
        low=float(row["lowPrice"]),
        quote_volume=float(row["quoteVolume"]),
    )


def _is_tradeable(symbol: str, excludes: list[str]) -> bool:
    if not symbol.endswith("USDT"):
        return False
    return not any(pat in symbol for pat in excludes)


def fetch(cfg, offline: bool = False) -> Snapshot:
    now = cfg.now()
    if offline:
        return _synthetic(cfg, now)

    watchlist = cfg.get("market", "watchlist", default=[])
    excludes = cfg.get("market", "exclude_patterns", default=[])
    min_vol = cfg.get("market", "min_quote_volume", default=0)
    top_n = cfg.get("market", "gainers_count", default=5)

    rows = _get(f"{SPOT}/ticker/24hr")
    universe = [
        _parse_ticker(r)
        for r in rows
        if _is_tradeable(r["symbol"], excludes) and float(r["quoteVolume"]) >= min_vol
    ]
    by_symbol = {t.symbol: t for t in universe}

    snap = Snapshot(generated_at=now)
    for sym in watchlist:
        if sym in by_symbol:
            snap.tickers[sym] = by_symbol[sym]

    ranked = sorted(universe, key=lambda t: t.change_pct, reverse=True)
    snap.gainers = ranked[:top_n]
    snap.losers = ranked[-top_n:][::-1]

    for sym in watchlist:
        try:
            klines = _get(f"{SPOT}/klines?symbol={sym}&interval=1h&limit=48")
            snap.sparklines[sym] = [float(k[4]) for k in klines]
        except MarketError:
            continue

    for sym in watchlist:
        try:
            data = _get(f"{FUTURES}/premiumIndex?symbol={sym}")
            snap.funding[sym] = float(data["lastFundingRate"]) * 100
        except (MarketError, KeyError):
            continue

    try:
        fng = _get(FNG)["data"][0]
        snap.fear_greed = (int(fng["value"]), _translate_fng(fng["value_classification"]))
    except (MarketError, KeyError, IndexError, ValueError):
        snap.fear_greed = None

    if not snap.tickers:
        raise MarketError("觀察名單沒有取得任何行情，中止產生內容")
    return snap


_FNG_ZH = {
    "Extreme Fear": "極度恐懼",
    "Fear": "恐懼",
    "Neutral": "中性",
    "Greed": "貪婪",
    "Extreme Greed": "極度貪婪",
}


def _translate_fng(label: str) -> str:
    return _FNG_ZH.get(label, label)


def _synthetic(cfg, now: dt.datetime) -> Snapshot:
    """離線測試用的假資料，以日期為種子所以同一天結果穩定。"""
    rng = random.Random(now.strftime("%Y%m%d"))
    base_prices = {"BTCUSDT": 96000, "ETHUSDT": 3300, "SOLUSDT": 185, "BNBUSDT": 690}
    snap = Snapshot(generated_at=now, offline=True)

    for sym in cfg.get("market", "watchlist", default=[]):
        seed_price = base_prices.get(sym, 100) * rng.uniform(0.9, 1.1)
        change = rng.uniform(-6, 6)
        high = seed_price * (1 + abs(change) / 100 * 0.6)
        low = seed_price * (1 - abs(change) / 100 * 0.6)
        snap.tickers[sym] = Ticker(sym, seed_price, change, high, low, rng.uniform(3e8, 4e9))
        snap.sparklines[sym] = [
            seed_price * (1 + math.sin(i / 6) * 0.02 + rng.uniform(-0.006, 0.006))
            for i in range(48)
        ]
        snap.funding[sym] = rng.uniform(-0.02, 0.03)

    fake = ["ARB", "OP", "TIA", "SUI", "APT", "INJ", "SEI", "JUP", "PYTH", "WLD"]
    rng.shuffle(fake)
    snap.gainers = [
        Ticker(f"{s}USDT", rng.uniform(0.5, 30), rng.uniform(8, 35), 0, 0, rng.uniform(3e7, 5e8))
        for s in fake[:5]
    ]
    snap.losers = [
        Ticker(f"{s}USDT", rng.uniform(0.5, 30), -rng.uniform(6, 20), 0, 0, rng.uniform(3e7, 5e8))
        for s in fake[5:10]
    ]
    snap.gainers.sort(key=lambda t: t.change_pct, reverse=True)
    snap.losers.sort(key=lambda t: t.change_pct)
    value = rng.randint(20, 85)
    label = "極度恐懼" if value < 25 else "恐懼" if value < 45 else "中性" if value < 55 else "貪婪" if value < 75 else "極度貪婪"
    snap.fear_greed = (value, label)
    return snap
