# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import GAMES, GAME_MAP
from db import Database
from fetch import fetch_game, fetch_next_draw
from lottery_calendar import (
    latest_expected_draw_date, next_issue, resolve_next_draw,
)
from models import GameRecommendation
from recommend import build_recommendations
from report import build_excel, build_html, build_markdown, build_stats


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "lottery.db"
REPORT_DIR = ROOT / "reports"
CN_TZ = timezone(timedelta(hours=8))

def now_cn() -> datetime:
    # 中国无夏令时，显式使用 UTC+8，避免服务器时区不同导致日期错位。
    return datetime.now(CN_TZ)


@dataclass
class FetchState:
    game: str
    expected_date: str | None = None
    latest_date: str | None = None
    fresh: bool = True
    attempts: int = 0
    error: str | None = None


def fetch_all(db: Database, selected: list[str], full: bool,
              run_dt: datetime, retries: int = 3,
              retry_wait: int = 180) -> dict[str, FetchState]:
    states: dict[str, FetchState] = {}
    for key in selected:
        g = GAME_MAP[key]
        existing = db.count_draws(key)
        need_full = full or existing < 500
        expected = latest_expected_draw_date(key, run_dt)
        state = FetchState(game=key, expected_date=expected.isoformat() if expected else None)
        print(f"[抓取] {g.name}（{'全量' if need_full else '增量'}）...", flush=True)

        for attempt in range(1, retries + 2):
            state.attempts = attempt
            try:
                draws = fetch_game(g, full=need_full)
                n = db.upsert_draws(draws)
                latest = db.latest(key)
                state.latest_date = latest.draw_date if latest else None
                state.fresh = (expected is None or
                               (latest is not None and latest.draw_date >= expected.isoformat()))
                state.error = None
                print(f"       {g.name}: 获取 {len(draws)} 期，写入 {n} 期，库内共 {db.count_draws(key)} 期", flush=True)
            except Exception as exc:  # noqa: BLE001
                state.error = str(exc)
                latest = db.latest(key)
                state.latest_date = latest.draw_date if latest else None
                state.fresh = (expected is None or
                               (latest is not None and latest.draw_date >= expected.isoformat()))
                print(f"       [警告] {g.name} 抓取失败：{exc}", file=sys.stderr, flush=True)

            print(f"       数据日期 {state.latest_date or '-'}，应有日期 "
                  f"{state.expected_date or '-'}，"
                  f"{'已更新' if state.fresh else '未更新'}", flush=True)
            if state.fresh or attempt >= retries + 1:
                break
            print(f"       等待 {retry_wait} 秒后重试（{attempt}/{retries}）...", flush=True)
            time.sleep(retry_wait)

        states[key] = state
    return states


def main() -> int:
    parser = argparse.ArgumentParser(description="彩票历史数据抓取 + 下一期号码参考生成器")
    parser.add_argument("--full", action="store_true", help="全量抓取历史（首次运行会自动全量）")
    parser.add_argument("--no-fetch", action="store_true", help="不抓取，直接用本地数据库生成报告")
    parser.add_argument("--games", default="", help="只处理指定玩法，逗号分隔，如 ssq,dlt,pl3")
    parser.add_argument("--salt", default="", help="评分随机种子盐，改变它会得到不同但同样合规的组合")
    parser.add_argument("--retries", type=int, default=3, help="数据未更新时的重试次数（默认 3）")
    parser.add_argument("--retry-wait", type=int, default=180, help="重试间隔秒数（默认 180）")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)

    selected = [x.strip() for x in args.games.split(",") if x.strip()] or [g.key for g in GAMES]
    bad = [x for x in selected if x not in GAME_MAP]
    if bad:
        print(f"未知玩法：{', '.join(bad)}", file=sys.stderr)
        return 2

    db = Database(DB_PATH)
    db.init()

    run_dt = now_cn()
    fetch_states: dict[str, FetchState] = {}
    if not args.no_fetch:
        fetch_states = fetch_all(
            db, selected, args.full, run_dt,
            retries=max(0, args.retries), retry_wait=max(1, args.retry_wait),
        )

    run_date = run_dt.strftime("%Y-%m-%d")
    run_id = run_dt.strftime("%Y%m%d_%H%M%S")

    recs: list[GameRecommendation] = []
    draws_by_game = {}
    for key in selected:
        g = GAME_MAP[key]
        draws = db.get_draws(key)
        draws_by_game[key] = draws
        if not draws:
            print(f"[跳过] {g.name}：本地没有数据", flush=True)
            continue
        latest = draws[-1]
        official_next = None
        try:
            official_next = fetch_next_draw(g)
        except Exception as exc:  # noqa: BLE001
            print(f"       [提示] {g.name} 官方下一期日期暂不可用，改用开奖日历：{exc}",
                  file=sys.stderr, flush=True)
        target, target_date, target_source = resolve_next_draw(
            key, latest.issue, latest.draw_date, official_next
        )
        try:
            sets = build_recommendations(g, draws, target, salt=args.salt)
        except Exception as exc:  # noqa: BLE001
            print(f"[跳过] {g.name} 推荐生成失败：{exc}", file=sys.stderr, flush=True)
            continue
        recs.append(GameRecommendation(
            game=key, target_issue=target, target_date=target_date,
            target_date_source=target_source,
            created_at=run_dt.isoformat(timespec="seconds"),
            sets=sets, latest=latest, sample_size=len(draws),
        ))
        date_text = target_date or "日期待定"
        print(f"[推荐] {g.name} 下一期 {target}，开奖日期 {date_text}：{len(sets)} 组", flush=True)

    if not recs:
        print("没有可生成报告的玩法。", file=sys.stderr)
        db.close()
        return 1

    stats = build_stats(draws_by_game)
    md = build_markdown(run_date, recs, stats)
    html_text = build_html(run_date, recs, stats)

    md_path = REPORT_DIR / f"report_{run_dt.strftime('%Y%m%d')}.md"
    html_path = REPORT_DIR / f"report_{run_dt.strftime('%Y%m%d')}.html"
    xlsx_path = REPORT_DIR / f"lottery_recommendations_{run_dt.strftime('%Y%m%d')}.xlsx"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    build_excel(xlsx_path, run_date, recs, stats)

    for src, name in [(md_path, "latest.md"), (html_path, "latest.html"), (xlsx_path, "latest.xlsx")]:
        shutil.copyfile(src, REPORT_DIR / name)

    db.save_recommendations(run_id, run_dt.isoformat(timespec="seconds"), recs)
    db.close()

    stale = [s for s in fetch_states.values() if not s.fresh]
    print("", flush=True)
    if stale:
        print("[警告] 以下玩法未更新到应有日期：", file=sys.stderr, flush=True)
        for s in stale:
            print(f"  {GAME_MAP[s.game].name}: 数据 {s.latest_date or '-'} / 应有 "
                  f"{s.expected_date or '-'}（重试 {s.attempts} 次）",
                  file=sys.stderr, flush=True)
        print("报告仍按本地最新数据生成，请稍后重跑。", file=sys.stderr, flush=True)

    print("", flush=True)
    print(f"完成：{len(recs)} 个玩法，报告已生成", flush=True)
    print(f"  Markdown: {md_path}", flush=True)
    print(f"  HTML    : {html_path}", flush=True)
    print(f"  Excel   : {xlsx_path}", flush=True)
    return 3 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
