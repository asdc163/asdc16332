"""已發布帳本。

排程會重跑（手動觸發、失敗重試、GitHub 偶發的重複派送），
沒有帳本就會重複發同一篇。帳本以「日期/slug」為鍵，發過的一律跳過。

發文是不可逆的對外動作，所以寧可漏發也不要重發：
只要成功送出（包含 504 這種送達但沒回 id 的情況）就先記帳。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

FILENAME = "published.json"


def path_for(cfg) -> Path:
    return cfg.data_dir / FILENAME


def load(cfg) -> dict:
    p = path_for(cfg)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 帳本壞掉時當成空的會造成重複發文，這裡必須擋下來。
        raise RuntimeError(f"{p} 內容不是合法 JSON，為避免重複發文已中止。請人工修復。")
    return data if isinstance(data, dict) else {}


def save(cfg, data: dict) -> Path:
    p = path_for(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return p


def key(day: str, slug: str) -> str:
    return f"{day}/{slug}"


def is_published(data: dict, day: str, slug: str) -> bool:
    entry = data.get(key(day, slug))
    return bool(entry) and entry.get("status") == "published"


def record(cfg, data: dict, day: str, slug: str, **fields) -> dict:
    data[key(day, slug)] = {
        "status": "published",
        "published_at": dt.datetime.now(cfg.tz).isoformat(),
        **fields,
    }
    save(cfg, data)
    return data


def count_on(data: dict, day: str) -> int:
    prefix = f"{day}/"
    return sum(1 for k, v in data.items() if k.startswith(prefix) and v.get("status") == "published")
