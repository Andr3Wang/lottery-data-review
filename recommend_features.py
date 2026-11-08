# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from collections import Counter
from statistics import mean, pstdev
from typing import Iterable, Sequence

from models import Draw


def percentile(values: Sequence[float], p: float) -> float:
    """线性插值百分位，p 取 0~1。"""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def counts(draws: Sequence[Draw], pool: int, window: int | None = None,
           extra: bool = False) -> dict[int, int]:
    subset = draws[-window:] if window else draws
    c: Counter[int] = Counter()
    for d in subset:
        c.update(d.extra if extra else d.numbers)
    return {n: c.get(n, 0) for n in range(1, pool + 1)}


def omissions(draws: Sequence[Draw], pool: int, extra: bool = False) -> dict[int, int]:
    """当前遗漏：距离上次开出已经过了多少期；从未开出则返回 len+1。"""
    out = {n: len(draws) + 1 for n in range(1, pool + 1)}
    seen: set[int] = set()
    for gap, d in enumerate(reversed(draws), start=0):
        nums = d.extra if extra else d.numbers
        for n in nums:
            if n in out and n not in seen:
                out[n] = gap
                seen.add(n)
        if len(seen) == pool:
            break
    return out


def average_gaps(draws: Sequence[Draw], pool: int, expected_gap: float,
                 extra: bool = False) -> dict[int, float]:
    positions: dict[int, list[int]] = {n: [] for n in range(1, pool + 1)}
    for i, d in enumerate(draws):
        for n in (d.extra if extra else d.numbers):
            if n in positions:
                positions[n].append(i)
    out: dict[int, float] = {}
    for n, ps in positions.items():
        if len(ps) >= 2:
            gaps = [b - a for a, b in zip(ps, ps[1:]) if b > a]
            out[n] = mean(gaps) if gaps else expected_gap
        else:
            out[n] = expected_gap
    return out


def zscore(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    mu = mean(values.values())
    sigma = pstdev(values.values())
    if sigma < 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sigma for k, v in values.items()}


def sums(draws: Sequence[Draw]) -> list[int]:
    return [sum(d.numbers) for d in draws]


def spans(draws: Sequence[Draw]) -> list[int]:
    return [max(d.numbers) - min(d.numbers) for d in draws if d.numbers]


def odd_counts(draws: Sequence[Draw], n: int | None = None) -> list[int]:
    out = []
    for d in draws:
        nums = d.numbers if n is None else d.numbers[:n]
        out.append(sum(1 for x in nums if x % 2 == 1))
    return out


def digit_counts(draws: Sequence[Draw], pos: int, base: int = 10,
                 window: int | None = None) -> dict[int, int]:
    subset = draws[-window:] if window else draws
    c: Counter[int] = Counter()
    for d in subset:
        if pos < len(d.numbers):
            c[d.numbers[pos]] += 1
    return {n: c.get(n, 0) for n in range(base)}


def digit_omissions(draws: Sequence[Draw], pos: int, base: int = 10) -> dict[int, int]:
    out = {n: len(draws) + 1 for n in range(base)}
    seen: set[int] = set()
    for gap, d in enumerate(reversed(draws), start=0):
        if pos < len(d.numbers):
            v = d.numbers[pos]
            if v in out and v not in seen:
                out[v] = gap
                seen.add(v)
        if len(seen) == base:
            break
    return out


def digit_average_gaps(draws: Sequence[Draw], pos: int, base: int = 10) -> dict[int, float]:
    """某个位置上各数字的历史平均间隔。"""
    positions: dict[int, list[int]] = {n: [] for n in range(base)}
    for i, d in enumerate(draws):
        if pos < len(d.numbers):
            v = d.numbers[pos]
            if v in positions:
                positions[v].append(i)
    out: dict[int, float] = {}
    for v, ps in positions.items():
        if len(ps) >= 2:
            gaps = [b - a for a, b in zip(ps, ps[1:]) if b > a]
            out[v] = mean(gaps) if gaps else float(base)
        else:
            out[v] = float(base)
    return out


def zone_counts(combo: Iterable[int], pool: int, zones: int) -> list[int]:
    counts_ = [0] * zones
    size = pool / zones
    for n in combo:
        idx = min(int((n - 1) / size), zones - 1)
        counts_[idx] += 1
    return counts_


def consecutive_pairs(combo: Sequence[int]) -> int:
    xs = sorted(combo)
    return sum(1 for a, b in zip(xs, xs[1:]) if b - a == 1)


def entropy(counts_: Sequence[int]) -> float:
    total = sum(counts_)
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counts_:
        if c > 0:
            p = c / total
            h -= p * math.log(p)
    max_h = math.log(len(counts_)) if len(counts_) > 1 else 1.0
    return h / max_h if max_h > 0 else 0.0


def all_same_tail(combo: Sequence[int]) -> bool:
    return len({n % 10 for n in combo}) == 1


def is_arithmetic_progression(combo: Sequence[int]) -> bool:
    xs = sorted(combo)
    if len(xs) < 3:
        return False
    diffs = {b - a for a, b in zip(xs, xs[1:])}
    return len(diffs) == 1


def birthday_heavy(combo: Sequence[int], threshold: int = 31) -> bool:
    return all(n <= threshold for n in combo)
