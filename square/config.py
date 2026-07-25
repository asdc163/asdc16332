"""設定檔載入與時區工具。"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@dataclass
class Config:
    raw: dict
    path: Path

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.raw["locale"]["timezone"])

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.tz)

    def get(self, *keys, default=None):
        node = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def out_dir(self) -> Path:
        return ROOT / self.raw["output"]["dir"]

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"


def load(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config(raw=raw, path=path)


def iso_week(day: dt.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"
