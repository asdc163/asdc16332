"""配圖產生器（純 PIL，不需要任何外部 API）。

四種版型：
  market_card       早報行情卡，含 48 小時走勢
  education_poster  教育系列直式海報
  leaderboard       漲跌幅榜
  weekly_card       週報整理

配色沿用幣安深色介面，圖卡在廣場的深色與淺色主題下都看得清楚。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .compose import arrow, fmt_pct, fmt_price, fmt_volume

BG = (11, 14, 17)
SURFACE = (24, 26, 32)
SURFACE_ALT = (30, 33, 40)
ACCENT = (240, 185, 11)
UP = (46, 189, 133)
DOWN = (246, 70, 93)
TEXT = (234, 236, 239)
MUTED = (132, 142, 156)
LINE = (43, 47, 54)

CJK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/opentype/unifont/unifont.otf",
]
NUM_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _first_existing(paths: list[str]) -> str | None:
    return next((p for p in paths if Path(p).exists()), None)


_CJK_PATH = _first_existing(CJK_FONTS)
_NUM_PATH = _first_existing(NUM_FONTS)


def font(size: int, numeric: bool = False) -> ImageFont.FreeTypeFont:
    path = (_NUM_PATH if numeric else None) or _CJK_PATH
    if path is None:
        return ImageFont.load_default(size)
    return ImageFont.truetype(path, size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    return int(draw.textlength(text, font=fnt))


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    """中英混排斷行：中文逐字量測，英文以空白為單位。"""
    lines: list[str] = []
    current = ""
    token = ""

    def flush_token():
        nonlocal current, token
        if not token:
            return
        candidate = current + token
        if _text_width(draw, candidate, fnt) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = token
        token = ""

    for ch in text:
        if ch == "\n":
            flush_token()
            lines.append(current)
            current = ""
            continue
        if ch.isascii() and not ch.isspace():
            token += ch
            continue
        flush_token()
        if ch.isspace():
            if current and _text_width(draw, current + ch, fnt) <= max_width:
                current += ch
            continue
        if _text_width(draw, current + ch, fnt) <= max_width or not current:
            current += ch
        else:
            lines.append(current)
            current = ch
    flush_token()
    if current:
        lines.append(current)
    return lines


def _rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _footer(draw: ImageDraw.ImageDraw, w: int, h: int, handle: str, note: str = ""):
    f = font(24)
    draw.line([(64, h - 96), (w - 64, h - 96)], fill=LINE, width=2)
    draw.text((64, h - 74), f"@{handle}", font=f, fill=MUTED)
    if note:
        tw = _text_width(draw, note, f)
        draw.text((w - 64 - tw, h - 74), note, font=f, fill=MUTED)


def _sparkline(draw, box, series: list[float], color):
    x0, y0, x1, y1 = box
    if len(series) < 2:
        return
    lo, hi = min(series), max(series)
    span = hi - lo or 1
    step = (x1 - x0) / (len(series) - 1)
    pts = [(x0 + i * step, y1 - (v - lo) / span * (y1 - y0)) for i, v in enumerate(series)]
    draw.polygon(
        [(x0, y1)] + pts + [(x1, y1)],
        fill=(color[0] // 8 + BG[0], color[1] // 8 + BG[1], color[2] // 8 + BG[2]),
    )
    draw.line(pts, fill=color, width=4, joint="curve")


# ---------------------------------------------------------------- 版型

def market_card(cfg, snap, path: Path) -> Path:
    w, h = cfg.get("output", "card_size", default=[1080, 1080])
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([(0, 0), (w, 8)], fill=ACCENT)
    d.text((64, 64), "每日行情快報", font=font(52), fill=TEXT)
    d.text(
        (64, 132),
        snap.generated_at.strftime("%Y/%m/%d %H:%M") + " 台北時間",
        font=font(28),
        fill=MUTED,
    )

    tickers = list(snap.tickers.values())[:4]
    top = 210
    row_h = 168
    for i, t in enumerate(tickers):
        y = top + i * row_h
        _rounded(d, [(56, y), (w - 56, y + row_h - 20)], 20, SURFACE)
        color = UP if t.change_pct > 0 else DOWN if t.change_pct < 0 else MUTED

        d.text((88, y + 26), t.base, font=font(40), fill=TEXT)
        d.text((88, y + 84), f"${fmt_price(t.last)}", font=font(46, numeric=True), fill=TEXT)

        badge = f"{arrow(t.change_pct)} {fmt_pct(t.change_pct)}"
        bw = _text_width(d, badge, font(30)) + 36
        _rounded(d, [(w - 88 - bw, y + 26), (w - 88, y + 74)], 12, SURFACE_ALT)
        d.text((w - 88 - bw + 18, y + 33), badge, font=font(30), fill=color)

        series = snap.sparklines.get(t.symbol)
        if series:
            _sparkline(d, (w - 88 - 280, y + 86, w - 88, y + 138), series, color)
        else:
            d.text(
                (w - 88 - 280, y + 100),
                f"量 {fmt_volume(t.quote_volume)}",
                font=font(28),
                fill=MUTED,
            )

    if snap.fear_greed:
        value, label = snap.fear_greed
        d.text((64, top + len(tickers) * row_h + 6), f"恐懼貪婪指數 {value}　{label}", font=font(30), fill=MUTED)

    note = "資料：幣安公開行情" + ("（離線示意）" if snap.offline else "")
    _footer(d, w, h, cfg.get("brand", "handle", default=""), note)
    img.save(path, quality=95)
    return path


def education_poster(cfg, spec: dict, path: Path) -> Path:
    w, h = cfg.get("output", "poster_size", default=[1080, 1350])
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([(0, 0), (16, h)], fill=ACCENT)

    label = f"{spec.get('track', '教學')}　第 {spec.get('index', 1)} 篇"
    d.text((72, 92), label, font=font(30), fill=ACCENT)

    title_font = font(66)
    lines = wrap(d, spec["title"], title_font, w - 160)
    y = 160
    for line in lines[:4]:
        d.text((72, y), line, font=title_font, fill=TEXT)
        y += 88

    y += 40
    d.line([(72, y), (w - 72, y)], fill=LINE, width=2)
    y += 56

    # 先量好結論區塊的高度，才知道條列可以用掉多少垂直空間
    point_font = font(40)
    num_font = font(34, numeric=True)
    take = spec.get("takeaway", "")
    take_font = font(38)
    take_lines = wrap(d, take, take_font, w - 240)[:4] if take else []
    block_h = 88 + len(take_lines) * 56 if take_lines else 0
    block_top = h - 140 - block_h

    points = spec.get("points", [])[:5]
    wrapped = [wrap(d, p, point_font, w - 220)[:3] for p in points]
    natural = sum(len(lines) * 52 + 48 for lines in wrapped)
    available = block_top - 40 - y
    # 條列少的時候把行距拉開填滿版面，多的時候收緊但不重疊
    slack = max(0, available - natural)
    extra = min(60, slack // len(points)) if points else 0

    for i, lines in enumerate(wrapped, 1):
        d.ellipse([(72, y), (72 + 52, y + 52)], fill=SURFACE_ALT)
        nw = _text_width(d, str(i), num_font)
        d.text((72 + 26 - nw // 2, y + 8), str(i), font=num_font, fill=ACCENT)
        for j, line in enumerate(lines):
            d.text((148, y + 2 + j * 52), line, font=point_font, fill=TEXT)
        y += len(lines) * 52 + 48 + extra

    if take_lines:
        _rounded(d, [(72, block_top), (w - 72, block_top + block_h)], 24, SURFACE)
        d.rectangle([(72, block_top), (80, block_top + block_h)], fill=ACCENT)
        d.text((116, block_top + 28), "重點", font=font(28), fill=ACCENT)
        ty = block_top + 74
        for line in take_lines:
            d.text((116, ty), line, font=take_font, fill=TEXT)
            ty += 56

    _footer(d, w, h, cfg.get("brand", "handle", default=""), "教育系列")
    img.save(path, quality=95)
    return path


def leaderboard(cfg, spec: dict, snap, path: Path) -> Path:
    w, h = cfg.get("output", "card_size", default=[1080, 1080])
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([(0, 0), (w, 8)], fill=ACCENT)
    d.text((64, 60), "24 小時漲跌幅", font=font(52), fill=TEXT)
    d.text((64, 128), snap.generated_at.strftime("%Y/%m/%d") + "　已濾除低流動性標的", font=font(26), fill=MUTED)

    col_w = (w - 160) // 2
    for col, (title, rows, color) in enumerate(
        [("漲幅", spec.get("gainers", []), UP), ("跌幅", spec.get("losers", []), DOWN)]
    ):
        x = 64 + col * (col_w + 32)
        _rounded(d, [(x, 196), (x + col_w, 196 + 60)], 12, SURFACE_ALT)
        d.text((x + 24, 210), title, font=font(34), fill=color)
        y = 288
        for t in rows[:5]:
            _rounded(d, [(x, y), (x + col_w, y + 104)], 16, SURFACE)
            d.text((x + 24, y + 16), t.base, font=font(36), fill=TEXT)
            d.text((x + 24, y + 60), fmt_pct(t.change_pct), font=font(32, numeric=True), fill=color)
            vol = fmt_volume(t.quote_volume)
            vw = _text_width(d, vol, font(26))
            d.text((x + col_w - 24 - vw, y + 64), vol, font=font(26), fill=MUTED)
            y += 120

    if snap.funding:
        d.text((64, 916), "資金費率　" + "　".join(
            f"{s.removesuffix('USDT')} {r:+.3f}%" for s, r in list(snap.funding.items())[:4]
        ), font=font(28), fill=MUTED)

    note = "資料：幣安公開行情" + ("（離線示意）" if snap.offline else "")
    _footer(d, w, h, cfg.get("brand", "handle", default=""), note)
    img.save(path, quality=95)
    return path


def weekly_card(cfg, snap, path: Path) -> Path:
    w, h = cfg.get("output", "card_size", default=[1080, 1080])
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([(0, 0), (w, 8)], fill=ACCENT)
    day = snap.generated_at.date()
    monday = day.fromordinal(day.toordinal() - day.weekday())
    d.text((64, 60), "週報", font=font(60), fill=TEXT)
    d.text((64, 140), f"{monday.strftime('%m/%d')} – {day.strftime('%m/%d')}", font=font(32, numeric=True), fill=ACCENT)

    y = 236
    for t in list(snap.tickers.values())[:4]:
        color = UP if t.change_pct > 0 else DOWN if t.change_pct < 0 else MUTED
        _rounded(d, [(56, y), (w - 56, y + 132)], 20, SURFACE)
        d.text((88, y + 22), t.base, font=font(38), fill=TEXT)
        d.text((88, y + 74), f"${fmt_price(t.last)}", font=font(36, numeric=True), fill=TEXT)
        pct = fmt_pct(t.change_pct)
        pw = _text_width(d, pct, font(44, numeric=True))
        d.text((w - 88 - pw, y + 30), pct, font=font(44, numeric=True), fill=color)
        rng_txt = f"區間 {fmt_price(t.low)} – {fmt_price(t.high)}"
        rw = _text_width(d, rng_txt, font(26))
        d.text((w - 88 - rw, y + 86), rng_txt, font=font(26), fill=MUTED)
        y += 148

    up, down = snap.breadth
    summary = f"觀察名單 {up} 漲 {down} 跌"
    if snap.fear_greed:
        summary += f"　情緒 {snap.fear_greed[0]}（{snap.fear_greed[1]}）"
    d.text((64, y + 12), summary, font=font(30), fill=MUTED)

    _footer(d, w, h, cfg.get("brand", "handle", default=""), "每週回顧")
    img.save(path, quality=95)
    return path


def render(cfg, post, snap, path: Path) -> Path:
    spec = post.image_spec
    kind = spec.get("type")
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "market_card":
        return market_card(cfg, snap, path)
    if kind == "education_poster":
        return education_poster(cfg, spec, path)
    if kind == "leaderboard":
        return leaderboard(cfg, spec, snap, path)
    if kind == "weekly_card":
        return weekly_card(cfg, snap, path)
    raise ValueError(f"未知的圖卡型別: {kind}")
