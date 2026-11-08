# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Draw:
    game: str
    issue: str
    draw_date: str          # YYYY-MM-DD
    numbers: list[int]
    extra: list[int] = field(default_factory=list)
    sales: float | None = None
    pool: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NextDraw:
    game: str
    issue: str | None
    draw_date: str | None
    source: str
    draw_time: str | None = None
    sale_end: str | None = None


@dataclass
class RecommendationSet:
    numbers: list[int]
    extra: list[int]
    score: float
    rationale: str


@dataclass
class GameRecommendation:
    game: str
    target_issue: str
    created_at: str
    sets: list[RecommendationSet]
    target_date: str | None = None
    target_date_source: str = "schedule"
    latest: Draw | None = None
    sample_size: int = 0
