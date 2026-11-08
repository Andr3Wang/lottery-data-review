# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any

import requests

from config import GameConfig
from models import Draw, NextDraw


class FetchError(RuntimeError):
    pass


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_date(value: str) -> str:
    return (value or "").split("(")[0].strip()


class CwlClient:
    """中国福利彩票网开奖查询接口。"""

    BASE = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.cwl.gov.cn/",
        })

    def _get(self, params: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                r = self.session.get(self.BASE, params=params, timeout=60)
                r.raise_for_status()
                data = r.json()
                if data.get("state") != 0:
                    raise FetchError(f"福彩接口返回异常: {data.get('message')}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < retries:
                    time.sleep(1.2 * attempt)
        raise FetchError(f"福彩接口请求失败: {last_err}")

    def fetch(self, game: GameConfig, full: bool = False) -> list[Draw]:
        # 官方接口单次最多返回约 2000+ 期；全量时一次取完即可。
        count = 10000 if full else 160
        data = self._get({"name": game.api_name, "issueCount": count})
        items = data.get("result") or []
        return [parse_cwl(game, item) for item in items]


class SportteryClient:
    """中国体彩网历史开奖接口。"""

    BASE = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    SALE_INFO = "https://webapi.sporttery.cn/gateway/lottery/getLottoSaleInfoV1.qry"
    HOME = "https://www.sporttery.cn/"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://static.sporttery.cn/",
            "Origin": "https://static.sporttery.cn",
        })
        # 先访问主页拿 Cookie，否则接口可能返回 567 风控页。
        try:
            self.session.get(self.HOME, timeout=20)
        except Exception:  # noqa: BLE001
            pass

    def _get_page(self, game_no: str, page: int, page_size: int = 100,
                  retries: int = 3) -> dict[str, Any]:
        params = {
            "gameNo": game_no, "provinceId": 0,
            "pageSize": page_size, "isVerify": 1, "pageNo": page,
        }
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                r = self.session.get(self.BASE, params=params, timeout=60)
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise FetchError(f"体彩接口返回异常: {data.get('errorMessage')}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < retries:
                    time.sleep(1.2 * attempt)
        raise FetchError(f"体彩接口请求失败: {last_err}")

    def fetch_next_draw(self, game: GameConfig) -> NextDraw | None:
        """读取体彩官方“当前销售期”信息。

        该接口目前稳定提供超级大乐透下一期期号/开奖时间；
        其他体彩数字玩法没有等价的官方“下一期”字段，由调用方回退到开奖日历。
        """
        if game.key != "dlt":
            return None

        params = {"param": f"{game.api_name},0", "isVerify": 1}
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                r = self.session.get(self.SALE_INFO, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise FetchError(f"体彩销售期接口返回异常: {data.get('errorMessage')}")
                value = data.get("value") or []
                if not value:
                    return None
                item = next(
                    (x for x in value if str(x.get("lotteryGameNum", "")) == game.api_name),
                    value[0],
                )
                issue = str(item.get("lotteryDrawNum") or "").strip()
                draw_time = str(item.get("lotteryDrawTime") or "").strip()
                draw_date = draw_time.split(" ")[0] if draw_time else None
                if not issue or not draw_date:
                    return None
                return NextDraw(
                    game=game.key,
                    issue=issue,
                    draw_date=draw_date,
                    source="sporttery_official",
                    draw_time=draw_time or None,
                    sale_end=str(item.get("lotterySaleEndtime") or "").strip() or None,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < 3:
                    time.sleep(1.2 * attempt)
        raise FetchError(f"体彩下一期日期请求失败: {last_err}")

    def fetch(self, game: GameConfig, full: bool = False) -> list[Draw]:
        page_size = 100
        max_pages = 120 if full else 2
        draws: list[Draw] = []
        total = None
        for page in range(1, max_pages + 1):
            data = self._get_page(game.api_name, page, page_size)
            value = data.get("value") or {}
            items = value.get("list") or []
            if not items:
                break
            draws.extend(parse_sporttery(game, item) for item in items)
            total = int(value.get("total") or 0)
            if total and page * page_size >= total:
                break
            time.sleep(0.25)
        return draws


def parse_cwl(game: GameConfig, item: dict[str, Any]) -> Draw:
    red = [int(x) for x in str(item.get("red", "")).split(",") if str(x).strip()]
    blue = [int(x) for x in str(item.get("blue", "")).split(",") if str(x).strip()]
    if game.key == "ssq":
        numbers, extra = red, blue[:1]
    elif game.key == "qlc":
        numbers, extra = red, blue[:1]
    elif game.key == "kl8":
        numbers, extra = red, []
    elif game.key == "fc3d":
        numbers, extra = red, []
    else:
        numbers, extra = red, blue
    return Draw(
        game=game.key,
        issue=str(item.get("code", "")).strip(),
        draw_date=_clean_date(str(item.get("date", ""))),
        numbers=numbers,
        extra=extra,
        sales=_to_float(item.get("sales")),
        pool=_to_float(item.get("poolmoney")),
        raw=item,
    )


def parse_sporttery(game: GameConfig, item: dict[str, Any]) -> Draw:
    nums = [int(x) for x in str(item.get("lotteryDrawResult", "")).split() if x.strip()]
    if game.key == "dlt":
        numbers, extra = nums[:5], nums[5:7]
    elif game.key == "qxc":
        numbers, extra = nums[:6], nums[6:7]
    else:
        numbers, extra = nums, []
    return Draw(
        game=game.key,
        issue=str(item.get("lotteryDrawNum", "")).strip(),
        draw_date=_clean_date(str(item.get("lotteryDrawTime", ""))),
        numbers=numbers,
        extra=extra,
        sales=_to_float(item.get("totalSaleAmount")),
        pool=_to_float(item.get("poolBalanceAfterdraw")),
        raw=item,
    )


def fetch_game(game: GameConfig, full: bool = False) -> list[Draw]:
    if game.provider == "cwl":
        return CwlClient().fetch(game, full=full)
    if game.provider == "sporttery":
        return SportteryClient().fetch(game, full=full)
    raise ValueError(f"未知数据源: {game.provider}")


def fetch_next_draw(game: GameConfig) -> NextDraw | None:
    if game.key == "dlt":
        return SportteryClient().fetch_next_draw(game)
    return None
