# -*- coding: utf-8 -*-
"""彩票市场休市日历。

2026 年使用官方公告；2027 年财政部/彩票中心公告尚未发布，
暂按国务院 2027 年节假日安排和近年彩票休市规则生成，状态标为 provisional。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MarketClosure:
    start: date
    end: date
    name: str
    status: str                 # official / provisional
    source: str


# 2026：财政部公告 2025 年第 14 号，福彩/体彩中心分别转发。
# 春节：2026-02-14 00:00 至 2026-02-23 24:00
# 国庆：2026-10-01 00:00 至 2026-10-04 24:00
# 2027：国务院安排春节 2027-02-05 至 02-13、国庆 10-01 至 10-07；
# 彩票市场按 2026 年规律暂推为春节 02-04 至 02-13、国庆 10-01 至 10-04。
CLOSURES: tuple[MarketClosure, ...] = (
    MarketClosure(
        date(2026, 2, 14), date(2026, 2, 23), "2026 年春节",
        "official", "财政部公告 2025 年第 14 号",
    ),
    MarketClosure(
        date(2026, 10, 1), date(2026, 10, 4), "2026 年国庆节",
        "official", "财政部公告 2025 年第 14 号",
    ),
    MarketClosure(
        date(2027, 2, 4), date(2027, 2, 13), "2027 年春节（临时）",
        "provisional", "国务院 2027 年节假日安排，待彩票休市公告确认",
    ),
    MarketClosure(
        date(2027, 10, 1), date(2027, 10, 4), "2027 年国庆节（临时）",
        "provisional", "国务院 2027 年节假日安排，待彩票休市公告确认",
    ),
)


def closure_for(day: date) -> MarketClosure | None:
    for closure in CLOSURES:
        if closure.start <= day <= closure.end:
            return closure
    return None


def is_market_closed(day: date) -> bool:
    return closure_for(day) is not None


def closures_between(start: date, end: date) -> list[MarketClosure]:
    if end < start:
        return []
    return [c for c in CLOSURES if c.start <= end and c.end >= start]


def has_provisional_closure(start: date, end: date) -> bool:
    return any(c.status == "provisional" for c in closures_between(start, end))
