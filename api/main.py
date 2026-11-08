# -*- coding: utf-8 -*-
"""轻量只读 API：FastAPI + sqlite3。

只做查询，不承担抓取/计算；每日更新仍由 run_daily.py 完成。
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import GAME_MAP, GAMES, PROBABILITY_NOTES  # noqa: E402
from models import Draw  # noqa: E402
from lottery_calendar import next_draw_date, source_label  # noqa: E402
from report import fmt_draw, fmt_nums  # noqa: E402

DB_PATH = Path(os.getenv("LOTTERY_DB", str(ROOT / "data" / "lottery.db")))

app = FastAPI(title="Lottery Data API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def row_to_draw(game: str, row: sqlite3.Row) -> dict[str, Any]:
    g = GAME_MAP[game]
    d = Draw(
        game=game,
        issue=row["issue"],
        draw_date=row["draw_date"],
        numbers=json.loads(row["numbers"]),
        extra=json.loads(row["extra"]),
        sales=row["sales"],
        pool=row["pool"],
    )
    return {
        "game": game,
        "name": g.name,
        "issue": d.issue,
        "draw_date": d.draw_date,
        "numbers": d.numbers,
        "extra": d.extra,
        "sales": d.sales,
        "pool": d.pool,
        "display": fmt_draw(game, d),
    }


def require_game(game: str):
    g = GAME_MAP.get(game)
    if not g:
        raise HTTPException(status_code=404, detail=f"未知玩法: {game}")
    return g


@app.get("/api/health")
def health():
    ok = DB_PATH.exists()
    return {"status": "ok" if ok else "db_missing", "db_exists": ok}


@app.get("/api/games")
def list_games():
    with closing(conn()) as c:
        rows = c.execute(
            """SELECT game, issue, draw_date FROM draws d
               WHERE issue = (SELECT issue FROM draws x WHERE x.game=d.game
                              ORDER BY x.draw_date DESC, x.issue DESC LIMIT 1)"""
        ).fetchall()
    latest = {r["game"]: r for r in rows}
    out = []
    for g in GAMES:
        r = latest.get(g.key)
        out.append({
            "key": g.key,
            "name": g.name,
            "provider": g.provider,
            "provider_name": "福利彩票" if g.provider == "cwl" else "体育彩票",
            "kind": g.kind,
            "draw_desc": g.draw_desc,
            "price": g.price,
            "pool": g.pool,
            "pick": g.pick,
            "extra_pick": g.extra_pick,
            "extra_pool": g.extra_pool,
            "digits": g.digits,
            "back_pool": g.back_pool,
            "latest_issue": r["issue"] if r else None,
            "latest_date": r["draw_date"] if r else None,
        })
    return out


@app.get("/api/latest")
def latest_all():
    out = []
    with closing(conn()) as c:
        for g in GAMES:
            row = c.execute(
                "SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC LIMIT 1",
                (g.key,),
            ).fetchone()
            if row:
                out.append(row_to_draw(g.key, row))
    return out


@app.get("/api/draws")
def draws(
    game: str = Query(..., description="玩法 key，如 ssq、dlt、pl3"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    require_game(game)
    with closing(conn()) as c:
        total = c.execute("SELECT COUNT(*) n FROM draws WHERE game=?", (game,)).fetchone()["n"]
        rows = c.execute(
            "SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC LIMIT ? OFFSET ?",
            (game, limit, offset),
        ).fetchall()
    return {
        "game": game,
        "name": GAME_MAP[game].name,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [row_to_draw(game, r) for r in rows],
    }


@app.get("/api/recommendations")
def recommendations(game: str = Query(..., description="玩法 key")):
    require_game(game)
    with closing(conn()) as c:
        run = c.execute(
            """SELECT run_id, created_at FROM recommendations
               WHERE game=? ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (game,),
        ).fetchone()
        if not run:
            return {"game": game, "name": GAME_MAP[game].name, "target_issue": None,
                    "target_date": None, "target_date_source": None,
                    "target_date_source_label": None, "created_at": None, "items": []}
        rows = c.execute(
            """SELECT * FROM recommendations
               WHERE run_id=? AND game=? ORDER BY rank ASC""",
            (run["run_id"], game),
        ).fetchall()

        target_date = rows[0]["target_date"] if rows else None
        target_source = rows[0]["target_date_source"] if rows else None
        if not target_date:
            latest = c.execute(
                "SELECT draw_date FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC LIMIT 1",
                (game,),
            ).fetchone()
            if latest:
                try:
                    target_date = next_draw_date(latest["draw_date"], game).isoformat()
                    target_source = "schedule_official"
                except Exception:  # noqa: BLE001
                    target_date = None

    items = []
    for r in rows:
        items.append({
            "rank": r["rank"],
            "numbers": json.loads(r["numbers"]),
            "extra": json.loads(r["extra"]),
            "score": r["score"],
            "rationale": r["rationale"],
            "display": fmt_draw(game, Draw(
                game=game, issue=r["target_issue"], draw_date="",
                numbers=json.loads(r["numbers"]), extra=json.loads(r["extra"]),
            )),
        })
    return {
        "game": game,
        "name": GAME_MAP[game].name,
        "target_issue": rows[0]["target_issue"] if rows else None,
        "target_date": target_date,
        "target_date_source": target_source,
        "target_date_source_label": source_label(target_source) if target_source else None,
        "created_at": run["created_at"],
        "items": items,
    }


@app.get("/api/stats/{game}")
def stats(game: str):
    g = require_game(game)
    with closing(conn()) as c:
        rows = c.execute(
            "SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC LIMIT 300",
            (game,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="没有历史数据")

    draws = [Draw(game, r["issue"], r["draw_date"], json.loads(r["numbers"]),
                  json.loads(r["extra"])) for r in rows]
    sums = [sum(d.numbers) for d in draws]
    spans = [max(d.numbers) - min(d.numbers) for d in draws if d.numbers]
    odd = [sum(1 for n in d.numbers if n % 2 == 1) for d in draws]
    freq: Counter[int] = Counter()
    for d in draws:
        freq.update(d.numbers)

    lo, hi = min(sums), max(sums)
    bucket_n = 8
    step = max((hi - lo) / bucket_n, 1)
    buckets = []
    for i in range(bucket_n):
        a = lo + i * step
        b = lo + (i + 1) * step
        buckets.append({
            "label": f"{a:.0f}-{b:.0f}",
            "count": sum(1 for x in sums if (a <= x < b) or (i == bucket_n - 1 and x == b)),
        })

    top = [{"number": n, "count": c_} for n, c_ in freq.most_common(10)]
    odd_dist = Counter(odd)
    pool_numbers = range(10) if g.kind == "digit" else range(1, g.pool + 1)
    return {
        "game": game,
        "name": g.name,
        "sample": len(draws),
        "avg_sum": round(sum(sums) / len(sums), 2),
        "std_sum": round((sum((x - sum(sums) / len(sums)) ** 2 for x in sums) / len(sums)) ** 0.5, 2),
        "avg_span": round(sum(spans) / len(spans), 2) if spans else 0,
        "top": top,
        "frequency": [{"number": n, "count": freq.get(n, 0)} for n in pool_numbers],
        "sum_distribution": buckets,
        "odd_distribution": [{"odd": k, "count": odd_dist.get(k, 0)}
                             for k in range(0, max(odd) + 1)],
    }


@app.get("/api/probability")
def probability():
    return [{"game": g.key, "name": g.name, **PROBABILITY_NOTES[g.key]} for g in GAMES]


# 本地开发时由 FastAPI 直接托管前端；生产环境交给 Nginx。
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="web")
