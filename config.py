# -*- coding: utf-8 -*-
"""彩票玩法配置。

数据来源：
- 福彩：中国福利彩票网官方开奖接口（cwl.gov.cn）
- 体彩：中国体彩网官方开奖接口（sporttery.cn）

说明：本工具只做历史数据统计与组合筛选，不改变任何玩法的中奖概率。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    key: str                 # 内部标识
    name: str                # 中文名
    provider: str            # cwl / sporttery
    api_name: str            # 福彩 name 参数，或体彩 gameNo
    kind: str                # lotto / digit / keno
    draw_desc: str           # 开奖时间描述
    price: int = 2           # 单注价格（元）
    pick: int = 0            # 乐透型：每注选几个
    pool: int = 0            # 乐透型：号码池大小
    extra_pick: int = 0      # 乐透型：附加区选几个
    extra_pool: int = 0      # 乐透型：附加区号码池大小
    digits: int = 0          # 数字型：位数
    back_pool: int = 0       # 7星彩后区号码池（0..back_pool-1）
    issue_width: int = 0     # 期号宽度（7=YYYYNNN，5=YYNNN）
    zones: int = 3           # 乐透型分区数（用于结构约束）


GAMES: list[GameConfig] = [
    GameConfig(
        key="ssq", name="双色球", provider="cwl", api_name="ssq",
        kind="lotto", draw_desc="每周二、四、日 21:15", price=2,
        pick=6, pool=33, extra_pick=1, extra_pool=16, issue_width=7, zones=3,
    ),
    GameConfig(
        key="dlt", name="超级大乐透", provider="sporttery", api_name="85",
        kind="lotto", draw_desc="每周一、三、六 21:25", price=2,
        pick=5, pool=35, extra_pick=2, extra_pool=12, issue_width=5, zones=3,
    ),
    GameConfig(
        key="qlc", name="七乐彩", provider="cwl", api_name="qlc",
        kind="lotto", draw_desc="每周一、三、五 21:15", price=2,
        pick=7, pool=30, issue_width=7, zones=3,
    ),
    GameConfig(
        key="kl8", name="快乐8", provider="cwl", api_name="kl8",
        kind="keno", draw_desc="每日 21:30", price=2,
        pick=10, pool=80, issue_width=7, zones=8,
    ),
    GameConfig(
        key="fc3d", name="福彩3D", provider="cwl", api_name="3d",
        kind="digit", draw_desc="每日 21:15", price=2,
        digits=3, issue_width=7,
    ),
    GameConfig(
        key="pl3", name="排列3", provider="sporttery", api_name="35",
        kind="digit", draw_desc="每日 21:25", price=2,
        digits=3, issue_width=5,
    ),
    GameConfig(
        key="pl5", name="排列5", provider="sporttery", api_name="350133",
        kind="digit", draw_desc="每日 21:25", price=2,
        digits=5, issue_width=5,
    ),
    GameConfig(
        key="qxc", name="7星彩", provider="sporttery", api_name="04",
        kind="digit", draw_desc="每周二、五、日 21:25", price=2,
        digits=6, back_pool=15, issue_width=5,
    ),
]

GAME_MAP: dict[str, GameConfig] = {g.key: g for g in GAMES}

# 概率速查（用于报告展示，均为理论值）
PROBABILITY_NOTES: dict[str, dict[str, str]] = {
    "ssq": {"top": "一等奖 1/17,721,088", "second": "二等奖约 1/1,181,406", "return": "约 51%"},
    "dlt": {"top": "一等奖 1/21,425,712", "second": "二等奖约 1/1,071,286", "return": "约 51%"},
    "qlc": {"top": "一等奖 1/2,035,800", "second": "二等奖约 1/290,829", "return": "约 50%"},
    "kl8": {"top": "选十中十 1/8,911,711", "second": "选十中九约 1/163,381", "return": "约 58%"},
    "fc3d": {"top": "直选 1/1,000", "second": "组三单注 3/1,000；组六单注 6/1,000", "return": "约 50%"},
    "pl3": {"top": "直选 1/1,000", "second": "组三单注 3/1,000；组六单注 6/1,000", "return": "约 50%"},
    "pl5": {"top": "一等奖 1/100,000", "second": "-", "return": "约 50%"},
    "qxc": {"top": "一等奖 1/15,000,000", "second": "-", "return": "约 50%"},
}
