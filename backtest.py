# -*- coding: utf-8 -*-
"""Walk-forward 回测：推荐策略 vs 随机基线。

核心原则：
1. 每期只用该期之前的数据生成推荐，绝不使用未来数据。
2. 推荐 5 注，随机基线也 5 注；随机基线重复多次取平均，降低抽样噪声。
3. 输出平均命中率、高命中代理指标、头奖命中数、差值的 bootstrap 置信区间和置换检验 p 值。
4. 对公平彩票，正确的预期结论是“没有显著优势”。回测是验伪工具，不是盈利证明。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from config import GAMES, GAME_MAP
from db import Database
from models import Draw
from recommend import build_recommendations


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
CN_TZ = timezone(timedelta(hours=8))


@dataclass
class TicketResult:
    main_hits: int
    extra_hits: int
    match_fraction: float
    high_hit: bool
    top_hit: bool


def evaluate_ticket(game, numbers: Sequence[int], extra: Sequence[int], draw: Draw) -> TicketResult:
    if game.kind == "lotto":
        main_hits = len(set(numbers) & set(draw.numbers))
        extra_hits = len(set(extra) & set(draw.extra))
        high_threshold = max(1, game.pick - 2)  # 双色球 4，大乐透 3，七乐彩 5
        top_hit = main_hits == game.pick and (
            game.extra_pick == 0 or extra_hits == game.extra_pick
        )
        return TicketResult(main_hits, extra_hits, main_hits / game.pick,
                            main_hits >= high_threshold, top_hit)

    if game.kind == "digit":
        position_hits = sum(1 for a, b in zip(numbers, draw.numbers) if a == b)
        high_threshold = max(1, game.digits - 1)  # 3D 2，排列5 4，7星彩 5
        back_hit = True
        if game.back_pool:
            back_hit = bool(extra and draw.extra and extra[0] == draw.extra[0])
        return TicketResult(position_hits, 1 if back_hit and game.back_pool else 0,
                            position_hits / game.digits,
                            position_hits >= high_threshold,
                            position_hits == game.digits and back_hit)

    if game.kind == "keno":
        main_hits = len(set(numbers) & set(draw.numbers))
        return TicketResult(main_hits, 0, main_hits / 10,
                            main_hits >= 8, main_hits == 10)

    raise ValueError(f"未知玩法类型: {game.kind}")


def random_ticket(game, rng: random.Random) -> tuple[list[int], list[int]]:
    if game.kind == "lotto":
        numbers = rng.sample(range(1, game.pool + 1), game.pick)
        extra = rng.sample(range(1, game.extra_pool + 1), game.extra_pick) if game.extra_pick else []
        return sorted(numbers), sorted(extra)
    if game.kind == "digit":
        numbers = [rng.randrange(10) for _ in range(game.digits)]
        extra = [rng.randrange(game.back_pool)] if game.back_pool else []
        return numbers, extra
    if game.kind == "keno":
        return sorted(rng.sample(range(1, 81), 10)), []
    raise ValueError(f"未知玩法类型: {game.kind}")


def batch_metrics(game, tickets: Iterable[tuple[Sequence[int], Sequence[int]]],
                  draw: Draw) -> dict:
    results = [evaluate_ticket(game, nums, extra, draw) for nums, extra in tickets]
    n = len(results)
    return {
        "tickets": n,
        "mean_main_hits": statistics.mean(r.main_hits for r in results) if n else 0.0,
        "mean_match_fraction": statistics.mean(r.match_fraction for r in results) if n else 0.0,
        "high_hits": sum(1 for r in results if r.high_hit),
        "top_hits": sum(1 for r in results if r.top_hit),
    }


def bootstrap_ci(values: Sequence[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.mean(sample))
    means.sort()
    return means[int(0.025 * (n - 1))], means[int(0.975 * (n - 1))]


def permutation_p_value(values: Sequence[float], n: int = 5000, seed: int = 0) -> float:
    if not values:
        return 1.0
    observed = abs(statistics.mean(values))
    rng = random.Random(seed)
    count = 0
    for _ in range(n):
        m = statistics.mean(v if rng.random() < 0.5 else -v for v in values)
        if abs(m) >= observed:
            count += 1
    return (count + 1) / (n + 1)


def _mean_dict(dicts: Sequence[dict]) -> dict:
    if not dicts:
        return {}
    keys = dicts[0].keys()
    return {k: statistics.mean(d[k] for d in dicts) for k in keys}


def backtest_game(game, draws: list[Draw], test_count: int, min_history: int,
                  random_trials: int, seed: int, fast: bool) -> dict:
    start = max(min_history, len(draws) - test_count)
    records = []
    for t in range(start, len(draws)):
        history = draws[:t]
        actual = draws[t]
        sets = build_recommendations(game, history, actual.issue, salt="backtest", fast=fast)
        strategy = batch_metrics(game, [(s.numbers, s.extra) for s in sets], actual)

        rng = random.Random(seed + t)
        random_runs = [
            batch_metrics(game, [random_ticket(game, rng) for _ in range(len(sets))], actual)
            for _ in range(random_trials)
        ]
        random_avg = _mean_dict(random_runs)
        records.append({
            "issue": actual.issue,
            "date": actual.draw_date,
            "strategy": strategy,
            "random": random_avg,
        })

    strategy_frac = [r["strategy"]["mean_match_fraction"] for r in records]
    random_frac = [r["random"]["mean_match_fraction"] for r in records]
    diffs = [s - r for s, r in zip(strategy_frac, random_frac)]
    ci_low, ci_high = bootstrap_ci(diffs, seed=seed)
    p_value = permutation_p_value(diffs, seed=seed)

    n_tickets = sum(r["strategy"]["tickets"] for r in records)
    strategy_high = sum(r["strategy"]["high_hits"] for r in records)
    strategy_top = sum(r["strategy"]["top_hits"] for r in records)
    random_high = sum(r["random"]["high_hits"] for r in records)
    random_top = sum(r["random"]["top_hits"] for r in records)

    return {
        "game": game.key,
        "name": game.name,
        "kind": game.kind,
        "test_draws": len(records),
        "start_date": records[0]["date"] if records else None,
        "end_date": records[-1]["date"] if records else None,
        "strategy": {
            "mean_match_fraction": round(statistics.mean(strategy_frac), 6) if strategy_frac else 0.0,
            "high_hits_total": strategy_high,
            "high_hit_rate": round(strategy_high / n_tickets, 6) if n_tickets else 0.0,
            "top_hits_total": strategy_top,
            "top_hit_rate": round(strategy_top / n_tickets, 8) if n_tickets else 0.0,
        },
        "random": {
            "mean_match_fraction": round(statistics.mean(random_frac), 6) if random_frac else 0.0,
            "high_hits_total": round(random_high, 3),
            "high_hit_rate": round(random_high / n_tickets, 6) if n_tickets else 0.0,
            "top_hits_total": round(random_top, 6),
            "top_hit_rate": round(random_top / n_tickets, 8) if n_tickets else 0.0,
        },
        "diff": {
            "mean_match_fraction": round(statistics.mean(diffs), 6) if diffs else 0.0,
            "ci95_low": round(ci_low, 6),
            "ci95_high": round(ci_high, 6),
            "p_value": round(p_value, 6),
        },
        "records": records,
    }


def build_markdown(results: list[dict], config: dict) -> str:
    lines = []
    lines.append(f"# 推荐模型回测（{config['date']}）")
    lines.append("")
    lines.append("> Walk-forward：每期只用该期之前的数据生成推荐；推荐 5 注，随机基线也 5 注，随机重复多次取平均。")
    lines.append("> 回测用于验伪，不证明未来有效。公平彩票的正确预期是“没有显著优势”。")
    lines.append("")
    lines.append("## 结果")
    lines.append("")
    lines.append("| 玩法 | 测试期数 | 策略命中率 | 随机命中率 | 差值 | 95% CI | p 值 | 高命中(策略/随机) | 头奖命中(策略/随机) |")
    lines.append("|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for r in results:
        s, b, d = r["strategy"], r["random"], r["diff"]
        lines.append(
            f"| {r['name']} | {r['test_draws']} | {s['mean_match_fraction']:.4f} | "
            f"{b['mean_match_fraction']:.4f} | {d['mean_match_fraction']:+.4f} | "
            f"[{d['ci95_low']:+.4f}, {d['ci95_high']:+.4f}] | {d['p_value']:.3f} | "
            f"{s['high_hits_total']} / {b['high_hits_total']:.1f} | "
            f"{s['top_hits_total']} / {b['top_hits_total']:.2f} |"
        )
    lines.append("")
    significant = [r for r in results if r["diff"]["p_value"] < 0.05 and
                   (r["diff"]["ci95_low"] > 0 or r["diff"]["ci95_high"] < 0)]
    if significant:
        lines.append("## 结论")
        lines.append("")
        lines.append("本次样本中出现了统计显著差异。优先检查前视偏差、过拟合、样本量或随机基线实现，"
                     "不要直接把回测结果当成未来收益。")
    else:
        lines.append("## 结论")
        lines.append("")
        lines.append("没有发现推荐策略显著优于随机基线。这个结果符合独立开奖的理论预期："
                     "历史统计只能改变号码的结构和分布，不能提高单注中奖概率。")
    lines.append("")
    lines.append("## 指标说明")
    lines.append("")
    lines.append("- 命中率：乐透型按主号码命中数 / 选号数；数字型按位置命中数 / 位数；快乐8 按命中数 / 10。")
    lines.append("- 高命中：双色球 4+ 红、大乐透 3+ 前区、七乐彩 5+、数字型差 1 位、快乐8 8+。这是代理指标，不是官方奖级。")
    lines.append("- 头奖：乐透型主号码全中且附加号全中；数字型全位置命中；快乐8 选十中十。")
    lines.append("- p 值：对每期差值做符号置换检验；CI 为对期数做 bootstrap。样本量小，统计功效有限。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward 回测：推荐策略 vs 随机基线")
    parser.add_argument("--games", default="ssq,dlt", help="玩法，all 或逗号分隔，默认 ssq,dlt")
    parser.add_argument("--draws", type=int, default=50, help="每个玩法测试期数")
    parser.add_argument("--min-history", type=int, default=300, help="最少历史期数")
    parser.add_argument("--random-trials", type=int, default=200, help="每期随机基线重复次数")
    parser.add_argument("--seed", type=int, default=20261108)
    parser.add_argument("--full-search", action="store_true", help="使用完整候选池，较慢")
    args = parser.parse_args()

    keys = [g.key for g in GAMES] if args.games.strip().lower() == "all" else [
        x.strip() for x in args.games.split(",") if x.strip()
    ]
    bad = [k for k in keys if k not in GAME_MAP]
    if bad:
        print(f"未知玩法：{', '.join(bad)}")
        return 2

    db = Database(ROOT / "data" / "lottery.db")
    db.init()
    results = []
    for key in keys:
        g = GAME_MAP[key]
        draws = db.get_draws(key)
        test_count = min(args.draws, max(0, len(draws) - args.min_history))
        if test_count < 5:
            print(f"[跳过] {g.name}: 可用测试期数不足（{test_count}）")
            continue
        print(f"[回测] {g.name}: {test_count} 期，随机基线 {args.random_trials} 次/期 ...", flush=True)
        results.append(backtest_game(
            g, draws, test_count, args.min_history, args.random_trials,
            args.seed, not args.full_search,
        ))
    db.close()

    if not results:
        print("没有可回测的玩法。")
        return 1

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_dt = datetime.now(CN_TZ)
    date_str = run_dt.strftime("%Y%m%d")
    config = {
        "date": run_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "games": keys,
        "draws": args.draws,
        "min_history": args.min_history,
        "random_trials": args.random_trials,
        "seed": args.seed,
        "fast": not args.full_search,
    }
    payload = {"generated_at": run_dt.isoformat(timespec="seconds"), "config": config, "results": results}
    json_path = REPORT_DIR / f"backtest_{date_str}.json"
    md_path = REPORT_DIR / f"backtest_{date_str}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(results, config), encoding="utf-8")

    print("")
    for r in results:
        d = r["diff"]
        print(f"{r['name']}: 策略 {r['strategy']['mean_match_fraction']:.4f} vs 随机 "
              f"{r['random']['mean_match_fraction']:.4f}, 差值 {d['mean_match_fraction']:+.4f}, "
              f"95% CI [{d['ci95_low']:+.4f}, {d['ci95_high']:+.4f}], p={d['p_value']:.3f}")
    print("")
    print(f"报告: {md_path}")
    print(f"数据: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
