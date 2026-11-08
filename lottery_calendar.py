# -*- coding: utf-8 -*-
"""开奖日历：官方下一期优先，缺失时按开奖星期和休市日历推算。"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from config import GAME_MAP
from market_holidays import has_provisional_closure, is_market_closed
from models import NextDraw

# Python weekday: Monday=0 ... Sunday=6
DRAW_WEEKDAYS: dict[str, set[int]] = {
    "ssq": {1, 3, 6},   # 周二、四、日
    "dlt": {0, 2, 5},   # 周一、三、六
    "qlc": {0, 2, 4},   # 周一、三、五
    "kl8": set(range(7)),
    "fc3d": set(range(7)),
    "pl3": set(range(7)),
    "pl5": set(range(7)),
    "qxc": {1, 4, 6},   # 周二、五、日
}

# 开奖后通常需要一段时间发布数据；22:30 定时任务远晚于这个阈值。
PUBLISH_BUFFER_MINUTES = 45


def _draw_start_time(game: str) -> time:
    """从配置的 draw_desc 中取开奖开始时间，解析失败时按 21:30 处理。"""
    text = GAME_MAP[game].draw_desc if game in GAME_MAP else ""
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return time(21, 30)
    hour, minute = int(match.group(1)), int(match.group(2))
    return time(hour, minute)


def draw_publish_cutoff(game: str, buffer_minutes: int = PUBLISH_BUFFER_MINUTES) -> time:
    start = datetime(2000, 1, 1, _draw_start_time(game).hour, _draw_start_time(game).minute)
    return (start + timedelta(minutes=buffer_minutes)).time()


def next_draw_date(draw_date: str, game: str) -> date:
    """下一开奖日；跳过周末规则之外的市场休市日。"""
    d = date.fromisoformat(draw_date)
    weekdays = DRAW_WEEKDAYS.get(game, set(range(7)))
    for i in range(1, 41):
        nd = d + timedelta(days=i)
        if nd.weekday() in weekdays and not is_market_closed(nd):
            return nd
    return d + timedelta(days=1)


def next_issue(issue: str, draw_date: str, game: str) -> str:
    """根据上期日期和玩法开奖日推下一期；最终以官方公布为准。"""
    issue = issue.strip()
    try:
        nxt = next_draw_date(draw_date, game)
    except Exception:  # noqa: BLE001
        nxt = None
    if len(issue) == 7:
        year, seq = int(issue[:4]), int(issue[4:])
        if nxt is not None and nxt.year != year:
            return f"{nxt.year}001"
        return f"{year}{seq + 1:03d}"
    if len(issue) == 5:
        yy, seq = int(issue[:2]), int(issue[2:])
        if nxt is not None and nxt.year != 2000 + yy:
            return f"{nxt.year % 100:02d}001"
        return f"{yy:02d}{seq + 1:03d}"
    return issue


def latest_expected_draw_date(game: str, now: datetime) -> date | None:
    """按当前时间计算“现在本应已经拿到”的最近一期开奖日期。

    开奖时间 + PUBLISH_BUFFER_MINUTES 之前，不要求当天数据已经发布。
    休市日不算应开奖日。
    """
    weekdays = DRAW_WEEKDAYS.get(game, set(range(7)))
    candidate = now.date()
    cutoff = draw_publish_cutoff(game)
    if now.time().replace(tzinfo=None) < cutoff:
        candidate -= timedelta(days=1)

    for _ in range(41):
        if candidate.weekday() in weekdays and not is_market_closed(candidate):
            return candidate
        candidate -= timedelta(days=1)
    return None


SOURCE_LABELS: dict[str, str] = {
    "sporttery_official": "体彩官方接口",
    "schedule_official": "官方开奖日 + 休市日历",
    "schedule_provisional": "开奖日历（2027休市待官方确认）",
    "schedule": "开奖日历",
}


def source_label(source: str | None) -> str:
    return SOURCE_LABELS.get(source or "", "开奖日历")


def resolve_next_draw(game: str, latest_issue: str, latest_date: str,
                      official: NextDraw | None = None) -> tuple[str, str | None, str]:
    """优先使用官方下一期接口；缺失时按官方开奖日和休市日历推算。

    返回（下一期期号、开奖日期、日期来源）。
    """
    if official and official.issue and official.draw_date:
        try:
            if (official.issue != latest_issue and
                    date.fromisoformat(official.draw_date) > date.fromisoformat(latest_date)):
                return official.issue, official.draw_date, official.source
        except ValueError:
            pass

    try:
        nxt_issue = next_issue(latest_issue, latest_date, game)
        nxt_date = next_draw_date(latest_date, game)
        provisional = has_provisional_closure(date.fromisoformat(latest_date), nxt_date)
        source = "schedule_provisional" if provisional else "schedule_official"
        return nxt_issue, nxt_date.isoformat(), source
    except Exception:  # noqa: BLE001
        return latest_issue, None, "schedule"
