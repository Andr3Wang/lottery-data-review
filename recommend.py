# -*- coding: utf-8 -*-
"""推荐引擎。

重要说明：
    彩票每期开奖是独立随机事件。下面的“评分”只是对历史频率、遗漏、
    结构平衡和大众选号偏好的描述性加权，不会提高任何一注的中奖概率。
    它真正能做的是：生成结构合理、彼此分散、尽量避开热门组合的号码，
    让推荐结果在“中奖后与人平分奖金”这一层上稍微不那么吃亏。
"""
from __future__ import annotations

import hashlib
import itertools
import math
import random
from collections import Counter
from statistics import mean, pstdev
from typing import Sequence

from config import GameConfig
from models import Draw, RecommendationSet
import recommend_features as F


def seed_for(game: str, issue: str, salt: str = "") -> int:
    text = f"{game}|{issue}|{salt}".encode("utf-8")
    return int(hashlib.sha256(text).hexdigest()[:16], 16)


def _softmax(scores: dict[int, float], temperature: float = 0.75) -> dict[int, float]:
    if not scores:
        return {}
    mx = max(scores.values())
    raw = {k: math.exp((v - mx) / temperature) for k, v in scores.items()}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def _weighted_sample(rng: random.Random, pool: Sequence[int],
                     weights: dict[int, float], k: int) -> list[int] | None:
    vals = [weights[n] for n in pool]
    for _ in range(30):
        picked = rng.choices(pool, weights=vals, k=k)
        if len(set(picked)) == k:
            return sorted(picked)
    return None


def _select_diverse(cands: list[tuple[float, list[int]]], n: int,
                    max_overlap: int, max_appearances: int | None = None
                    ) -> list[tuple[float, list[int]]]:
    cands = sorted(cands, key=lambda x: (-x[0], x[1]))
    chosen: list[tuple[float, list[int]]] = []
    used: Counter[int] = Counter()

    def ok(combo: list[int]) -> bool:
        if max_appearances is None:
            return True
        return all(used[x] + 1 <= max_appearances for x in combo)

    for score, combo in cands:
        if ok(combo) and all(len(set(combo) & set(c[1])) <= max_overlap for c in chosen):
            chosen.append((score, combo))
            used.update(combo)
            if len(chosen) >= n:
                return chosen
    # 若出现次数上限导致不足，放宽上限补足，但仍保持两两重叠约束。
    for score, combo in cands:
        if combo in [c[1] for c in chosen]:
            continue
        if all(len(set(combo) & set(c[1])) <= max_overlap for c in chosen):
            chosen.append((score, combo))
            if len(chosen) >= n:
                break
    return chosen


def _select_diverse_digit(cands: list[tuple[float, list[int]]], n: int,
                          min_diff: int = 2, max_appearances: int | None = None
                          ) -> list[tuple[float, list[int]]]:
    """数字型按“位”比较，要求任意两组至少有 min_diff 位不同。"""
    cands = sorted(cands, key=lambda x: (-x[0], x[1]))
    chosen: list[tuple[float, list[int]]] = []
    used: Counter[int] = Counter()

    def ok(combo: list[int]) -> bool:
        if max_appearances is None:
            return True
        return all(used[x] + 1 <= max_appearances for x in combo)

    for score, combo in cands:
        if ok(combo) and all(sum(1 for a, b in zip(combo, c[1]) if a != b) >= min_diff
                             for c in chosen):
            chosen.append((score, combo))
            used.update(combo)
            if len(chosen) >= n:
                return chosen
    for score, combo in cands:
        if combo in [c[1] for c in chosen]:
            continue
        if all(sum(1 for a, b in zip(combo, c[1]) if a != b) >= min_diff for c in chosen):
            chosen.append((score, combo))
            if len(chosen) >= n:
                break
    return chosen


class LottoRecommender:
    def __init__(self, game: GameConfig, draws: list[Draw], rng: random.Random):
        if len(draws) < 30:
            raise ValueError(f"{game.name} 历史数据不足（{len(draws)} 期）")
        self.g = game
        self.draws = draws
        self.rng = rng
        self.pool = list(range(1, game.pool + 1))
        self.last = draws[-1]

        c30 = F.counts(draws, game.pool, 30)
        c100 = F.counts(draws, game.pool, 100)
        c300 = F.counts(draws, game.pool, 300)
        gap = F.omissions(draws, game.pool)
        avg = F.average_gaps(draws, game.pool, game.pool / max(game.pick, 1))
        z30, z100, z300 = F.zscore(c30), F.zscore(c100), F.zscore(c300)
        zom = F.zscore({n: min(gap[n] / max(avg[n], 1.0), 3.0) for n in self.pool})

        # 四因子评分：短期热度 32% + 中期热度 23% + 长期热度 15% + 遗漏回补 30%
        self.base = {
            n: 0.32 * z30[n] + 0.23 * z100[n] + 0.15 * z300[n] + 0.30 * zom[n]
            for n in self.pool
        }
        self.weights = _softmax(self.base, 0.72)
        self.c30, self.gap, self.avg = c30, gap, avg

        hs = F.sums(draws[-300:])
        self.sum_q10 = F.percentile(hs, 0.10)
        self.sum_q90 = F.percentile(hs, 0.90)
        self.sum_med = F.percentile(hs, 0.50)
        self.sum_std = pstdev(hs) if len(hs) > 1 else 1.0
        self.odd_allowed = self._odd_range()
        self.last_set = set(self.last.numbers)

    def _odd_range(self) -> range:
        k = self.g.pick
        if k == 7:
            return range(3, 5)      # 3~4 奇
        if k == 5:
            return range(2, 4)      # 2~3 奇
        return range(2, 5)          # 2~4 奇

    def _pass(self, combo: list[int], strict: bool = True) -> bool:
        k = self.g.pick
        s = sum(combo)
        if strict and not (self.sum_q10 <= s <= self.sum_q90):
            return False
        odd = sum(1 for n in combo if n % 2 == 1)
        if strict and odd not in self.odd_allowed:
            return False
        big = sum(1 for n in combo if n > self.g.pool / 2)
        if strict and not (k // 2 <= big <= k - k // 2 + 1):
            return False
        zones = F.zone_counts(combo, self.g.pool, self.g.zones)
        if strict:
            if min(zones) < 1 or max(zones) > max(3, k // 2 + 1):
                return False
        if strict and F.consecutive_pairs(combo) > 1:
            return False
        # 双色球/大乐透前区：硬性要求至少一个 >31 的号，避开生日号扎堆。
        if strict and self.g.pool > 31 and all(n <= 31 for n in combo):
            return False
        overlap = len(self.last_set & set(combo))
        if strict and overlap > (2 if k >= 7 else 1):
            return False
        return True

    def _score(self, combo: list[int], strict: bool = True) -> float:
        k = self.g.pick
        base = mean(self.base[n] for n in combo)
        odd = sum(1 for n in combo if n % 2 == 1)
        odd_balance = 1.0 - abs(odd - k / 2) / max(k / 2, 0.5)
        zones = F.zone_counts(combo, self.g.pool, self.g.zones)
        zone_balance = F.entropy(zones)
        s = sum(combo)
        sum_fit = math.exp(-0.5 * ((s - self.sum_med) / max(self.sum_std, 1.0)) ** 2)
        anti = 0.0
        if self.g.pool > 31 and any(n > 31 for n in combo):
            anti += 0.12
        if not F.all_same_tail(combo):
            anti += 0.03
        if not F.is_arithmetic_progression(combo):
            anti += 0.03
        if F.consecutive_pairs(combo) <= 1:
            anti += 0.03
        jitter = self.rng.uniform(0.0, 0.08)
        return base + 0.25 * odd_balance + 0.20 * zone_balance + 0.20 * sum_fit + anti + jitter

    def _extra_candidates(self) -> list[list[int]]:
        g = self.g
        if g.extra_pick <= 0:
            return [[] for _ in range(5)]
        ep, pool = g.extra_pick, g.extra_pool
        c30 = F.counts(self.draws, pool, 30, extra=True)
        c100 = F.counts(self.draws, pool, 100, extra=True)
        gap = F.omissions(self.draws, pool, extra=True)
        avg = F.average_gaps(self.draws, pool, pool / max(ep, 1), extra=True)
        z30, z100 = F.zscore(c30), F.zscore(c100)
        zom = F.zscore({n: min(gap[n] / max(avg[n], 1.0), 3.0) for n in range(1, pool + 1)})
        sc = {n: 0.36 * z30[n] + 0.24 * z100[n] + 0.40 * zom[n] for n in range(1, pool + 1)}

        if ep == 1:
            order = sorted(range(1, pool + 1), key=lambda n: -sc[n])
            return [[n] for n in order[:5]]
        combos = [list(c) for c in itertools.combinations(range(1, pool + 1), ep)]
        combos.sort(key=lambda c: -mean(sc[n] for n in c))
        chosen: list[list[int]] = []
        for c in combos:
            if all(len(set(c) & set(x)) <= ep - 1 for x in chosen):
                chosen.append(c)
                if len(chosen) >= 5:
                    break
        return chosen

    def recommend(self, n_sets: int = 5, fast: bool = False) -> list[RecommendationSet]:
        k = self.g.pick
        candidates: list[tuple[float, list[int]]] = []
        target = n_sets * (500 if fast else 3000)
        attempts_limit = 10000 if fast else 60000
        min_needed = n_sets * (5 if fast else 20)
        for strict in (True, False):
            attempts = 0
            while len(candidates) < target and attempts < attempts_limit:
                attempts += 1
                combo = _weighted_sample(self.rng, self.pool, self.weights, k)
                if combo is None or not self._pass(combo, strict=strict):
                    continue
                candidates.append((self._score(combo, strict=strict), combo))
            if len(candidates) >= min_needed:
                break

        max_overlap = 3 if k >= 7 else 2
        picked = _select_diverse(candidates, n_sets, max_overlap, max_appearances=3)
        if not picked:
            picked = sorted(candidates, key=lambda x: -x[0])[:n_sets]
        extra_sets = self._extra_candidates()

        out: list[RecommendationSet] = []
        for i, (score, combo) in enumerate(picked):
            extra = extra_sets[i % len(extra_sets)] if extra_sets else []
            out.append(RecommendationSet(
                numbers=combo,
                extra=extra,
                score=round(60.0 + 40.0 * (score - picked[-1][0]) /
                            max(picked[0][0] - picked[-1][0], 1e-9), 2) if len(picked) > 1 else 80.0,
                rationale=self._rationale(combo, extra),
            ))
        return out

    def _rationale(self, combo: list[int], extra: list[int]) -> str:
        g = self.g
        by_hot = sorted(combo, key=lambda n: -self.base[n])[:2]
        by_om = sorted(combo, key=lambda n: -min(self.gap[n] / max(self.avg[n], 1.0), 3.0))[:1]
        odd = sum(1 for n in combo if n % 2 == 1)
        big = sum(1 for n in combo if n > g.pool / 2)
        zones = F.zone_counts(combo, g.pool, g.zones)
        s = sum(combo)
        parts = [
            f"热号 {by_hot[0]:02d}(近30期{self.c30[by_hot[0]]}次)",
            f"回补 {by_om[0]:02d}(遗漏{self.gap[by_om[0]]}期/均{self.avg[by_om[0]]:.1f})",
            f"奇偶{odd}:{g.pick - odd} 大小{big}:{g.pick - big}",
            f"和值{s}(中位{self.sum_med:.0f})",
            "分区" + ":".join(str(x) for x in zones),
        ]
        if g.pool > 31 and any(n > 31 for n in combo):
            parts.append("含>31号，避开生日扎堆")
        if extra:
            label = "蓝球" if g.key == "ssq" else "后区"
            parts.append(label + "/".join(f"{n:02d}" for n in extra))
        return "；".join(parts)


class DigitRecommender:
    def __init__(self, game: GameConfig, draws: list[Draw], rng: random.Random):
        if len(draws) < 30:
            raise ValueError(f"{game.name} 历史数据不足（{len(draws)} 期）")
        self.g = game
        self.draws = draws
        self.rng = rng
        self.pos_scores: list[dict[int, float]] = []
        self.pos_weights: list[dict[int, float]] = []
        self.pos_c30: list[dict[int, int]] = []
        self.pos_gap: list[dict[int, int]] = []
        self.pos_avg: list[dict[int, float]] = []
        self.pos_base = 10

        for p in range(game.digits):
            c30 = F.digit_counts(draws, p, 10, 30)
            c100 = F.digit_counts(draws, p, 10, 100)
            gap = F.digit_omissions(draws, p, 10)
            avg = F.digit_average_gaps(draws, p, 10)
            z30, z100 = F.zscore(c30), F.zscore(c100)
            zom = F.zscore({d: min(gap[d] / max(avg[d], 1.0), 3.0) for d in range(10)})
            sc = {d: 0.35 * z30[d] + 0.25 * z100[d] + 0.40 * zom[d] for d in range(10)}
            self.pos_scores.append(sc)
            self.pos_weights.append(_softmax(sc, 0.8))
            self.pos_c30.append(c30)
            self.pos_gap.append(gap)
            self.pos_avg.append(avg)

        hs = [sum(d.numbers) for d in draws[-300:]]
        self.sum_q10, self.sum_q90 = F.percentile(hs, 0.10), F.percentile(hs, 0.90)
        self.sum_med, self.sum_std = F.percentile(hs, 0.50), (pstdev(hs) if len(hs) > 1 else 1.0)
        self.spans = [max(d.numbers) - min(d.numbers) for d in draws[-300:] if d.numbers]
        self.span_q10, self.span_q90 = F.percentile(self.spans, 0.10), F.percentile(self.spans, 0.90)

        self.back_scores: dict[int, float] = {}
        self.back_top: list[int] = []
        if game.back_pool:
            pool = game.back_pool
            vals = [d.extra[0] for d in draws if d.extra]
            c30 = {n: sum(1 for v in vals[-30:] if v == n) for n in range(pool)}
            c100 = {n: sum(1 for v in vals[-100:] if v == n) for n in range(pool)}
            gap = {n: len(vals) + 1 for n in range(pool)}
            for n in range(pool):
                for i, v in enumerate(reversed(vals)):
                    if v == n:
                        gap[n] = i
                        break
            z30, z100 = F.zscore(c30), F.zscore(c100)
            zom = F.zscore({n: min(gap[n] / max(pool, 1.0), 3.0) for n in range(pool)})
            self.back_scores = {n: 0.35 * z30[n] + 0.25 * z100[n] + 0.40 * zom[n] for n in range(pool)}
            self.back_top = sorted(range(pool), key=lambda n: -self.back_scores[n])[:5]

    def _pass(self, combo: list[int], strict: bool = True) -> bool:
        s = sum(combo)
        if strict and not (self.sum_q10 <= s <= self.sum_q90):
            return False
        span = max(combo) - min(combo)
        if strict and self.g.digits >= 3 and not (self.span_q10 <= span <= self.span_q90):
            return False
        odd = sum(1 for n in combo if n % 2 == 1)
        k = self.g.digits
        lo, hi = (1, 2) if k == 3 else ((2, 3) if k == 5 else (2, 4))
        if strict and not (lo <= odd <= hi):
            return False
        if strict and len(set(combo)) == 1:
            return False
        if strict and F.is_arithmetic_progression(combo):
            return False
        return True

    def _score(self, combo: list[int]) -> float:
        k = len(combo)
        base = mean(self.pos_scores[p][d] for p, d in enumerate(combo))
        s = sum(combo)
        sum_fit = math.exp(-0.5 * ((s - self.sum_med) / max(self.sum_std, 1.0)) ** 2)
        odd = sum(1 for n in combo if n % 2 == 1)
        odd_balance = 1.0 - abs(odd - k / 2) / max(k / 2, 0.5)
        span = max(combo) - min(combo)
        span_fit = math.exp(-0.5 * ((span - (self.span_q10 + self.span_q90) / 2) /
                                   max((self.span_q90 - self.span_q10) / 2, 1.0)) ** 2)
        return base + 0.25 * sum_fit + 0.15 * odd_balance + 0.10 * span_fit + self.rng.uniform(0, 0.08)

    def recommend(self, n_sets: int = 5, fast: bool = False) -> list[RecommendationSet]:
        k = self.g.digits
        pool = list(range(10))
        weights = [self.pos_weights[p] for p in range(k)]
        cands: list[tuple[float, list[int]]] = []
        target = n_sets * (500 if fast else 3000)
        attempts_limit = 10000 if fast else 60000
        min_needed = n_sets * (5 if fast else 10)
        for strict in (True, False):
            attempts = 0
            while len(cands) < target and attempts < attempts_limit:
                attempts += 1
                combo = [self.rng.choices(pool, weights=[weights[p][d] for d in pool], k=1)[0]
                         for p in range(k)]
                if not self._pass(combo, strict=strict):
                    continue
                cands.append((self._score(combo), combo))
            if len(cands) >= min_needed:
                break
        picked = _select_diverse_digit(cands, n_sets, min_diff=2, max_appearances=3)
        if not picked:
            picked = sorted(cands, key=lambda x: -x[0])[:n_sets]

        out: list[RecommendationSet] = []
        for i, (score, combo) in enumerate(picked):
            extra = [self.back_top[i % len(self.back_top)]] if self.back_top else []
            if len(picked) > 1:
                norm = 60.0 + 40.0 * (score - picked[-1][0]) / max(picked[0][0] - picked[-1][0], 1e-9)
            else:
                norm = 80.0
            out.append(RecommendationSet(
                numbers=combo, extra=extra, score=round(norm, 2),
                rationale=self._rationale(combo, extra),
            ))
        return out

    def _rationale(self, combo: list[int], extra: list[int]) -> str:
        parts = []
        for p, d in enumerate(combo):
            parts.append(f"{'百十个'[p] if p < 3 else f'第{p+1}位'}{d}"
                         f"(30期{self.pos_c30[p][d]}次/遗漏{self.pos_gap[p][d]})")
        parts.append(f"和值{sum(combo)}")
        parts.append(f"跨度{max(combo)-min(combo)}")
        odd = sum(1 for n in combo if n % 2 == 1)
        parts.append(f"奇偶{odd}:{len(combo)-odd}")
        if extra:
            parts.append(f"后区{extra[0]:02d}")
        return "；".join(parts)


class KenoRecommender:
    def __init__(self, game: GameConfig, draws: list[Draw], rng: random.Random):
        if len(draws) < 30:
            raise ValueError(f"{game.name} 历史数据不足（{len(draws)} 期）")
        self.g = game
        self.draws = draws
        self.rng = rng
        self.pool = list(range(1, 81))
        c30 = F.counts(draws, 80, 30)
        c100 = F.counts(draws, 80, 100)
        c300 = F.counts(draws, 80, 300)
        gap = F.omissions(draws, 80)
        avg = F.average_gaps(draws, 80, 4.0)
        z30, z100, z300 = F.zscore(c30), F.zscore(c100), F.zscore(c300)
        zom = F.zscore({n: min(gap[n] / max(avg[n], 1.0), 3.0) for n in self.pool})
        self.base = {
            n: 0.32 * z30[n] + 0.23 * z100[n] + 0.15 * z300[n] + 0.30 * zom[n]
            for n in self.pool
        }
        self.weights = _softmax(self.base, 0.75)
        self.c30, self.gap, self.avg = c30, gap, avg

        # 用历史每期 20 个号中随机抽 10 个，近似 10 号组合的和值分布
        sample_sums = []
        for d in draws[-300:]:
            for _ in range(20):
                sample_sums.append(sum(self.rng.sample(d.numbers, min(10, len(d.numbers)))))
        self.sum_q10, self.sum_q90 = F.percentile(sample_sums, 0.10), F.percentile(sample_sums, 0.90)
        self.sum_med, self.sum_std = F.percentile(sample_sums, 0.50), (
            pstdev(sample_sums) if len(sample_sums) > 1 else 1.0)

    def _pass(self, combo: list[int], strict: bool = True) -> bool:
        s = sum(combo)
        if strict and not (self.sum_q10 <= s <= self.sum_q90):
            return False
        odd = sum(1 for n in combo if n % 2 == 1)
        if strict and not (4 <= odd <= 6):
            return False
        zones = F.zone_counts(combo, 80, 8)
        if strict and (sum(1 for z in zones if z > 0) < 5 or max(zones) > 3):
            return False
        if strict and F.consecutive_pairs(combo) > 3:
            return False
        return True

    def _score(self, combo: list[int]) -> float:
        base = mean(self.base[n] for n in combo)
        s = sum(combo)
        sum_fit = math.exp(-0.5 * ((s - self.sum_med) / max(self.sum_std, 1.0)) ** 2)
        zones = F.zone_counts(combo, 80, 8)
        zone_balance = F.entropy(zones)
        odd = sum(1 for n in combo if n % 2 == 1)
        odd_balance = 1.0 - abs(odd - 5) / 5.0
        return base + 0.25 * zone_balance + 0.20 * sum_fit + 0.15 * odd_balance + self.rng.uniform(0, 0.08)

    def recommend(self, n_sets: int = 5, fast: bool = False) -> list[RecommendationSet]:
        cands: list[tuple[float, list[int]]] = []
        target = n_sets * (800 if fast else 3000)
        attempts_limit = 15000 if fast else 60000
        min_needed = n_sets * (5 if fast else 10)
        for strict in (True, False):
            attempts = 0
            while len(cands) < target and attempts < attempts_limit:
                attempts += 1
                combo = _weighted_sample(self.rng, self.pool, self.weights, 10)
                if combo is None or not self._pass(combo, strict=strict):
                    continue
                cands.append((self._score(combo), combo))
            if len(cands) >= min_needed:
                break
        picked = _select_diverse(cands, n_sets, 4, max_appearances=3)
        out: list[RecommendationSet] = []
        for i, (score, combo) in enumerate(picked):
            if len(picked) > 1:
                norm = 60.0 + 40.0 * (score - picked[-1][0]) / max(picked[0][0] - picked[-1][0], 1e-9)
            else:
                norm = 80.0
            zones = F.zone_counts(combo, 80, 8)
            hot = sorted(combo, key=lambda n: -self.base[n])[:2]
            rationale = (f"热号 {hot[0]:02d}/{hot[1]:02d}；"
                         f"和值{sum(combo)}；奇偶{sum(1 for n in combo if n%2)}:"
                         f"{10-sum(1 for n in combo if n%2)}；"
                         f"八区分布{':'.join(str(z) for z in zones)}")
            out.append(RecommendationSet(numbers=combo, extra=[], score=round(norm, 2),
                                          rationale=rationale))
        return out


def build_recommendations(game: GameConfig, draws: list[Draw],
                          target_issue: str, salt: str = "",
                          fast: bool = False) -> list[RecommendationSet]:
    rng = random.Random(seed_for(game.key, target_issue, salt))
    if game.kind == "lotto":
        return LottoRecommender(game, draws, rng).recommend(5, fast=fast)
    if game.kind == "digit":
        return DigitRecommender(game, draws, rng).recommend(5, fast=fast)
    if game.kind == "keno":
        return KenoRecommender(game, draws, rng).recommend(5, fast=fast)
    raise ValueError(f"未知玩法类型: {game.kind}")
