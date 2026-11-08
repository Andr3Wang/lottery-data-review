# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from models import Draw, GameRecommendation


SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    game       TEXT NOT NULL,
    issue      TEXT NOT NULL,
    draw_date  TEXT NOT NULL,
    numbers    TEXT NOT NULL,
    extra      TEXT NOT NULL,
    sales      REAL,
    pool       REAL,
    raw        TEXT,
    PRIMARY KEY (game, issue)
);
CREATE INDEX IF NOT EXISTS idx_draws_game_date ON draws(game, draw_date);

CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    summary    TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    run_id       TEXT NOT NULL,
    game         TEXT NOT NULL,
    target_issue TEXT NOT NULL,
    rank         INTEGER NOT NULL,
    numbers      TEXT NOT NULL,
    extra        TEXT NOT NULL,
    score        REAL NOT NULL,
    rationale    TEXT,
    target_date  TEXT,
    target_date_source TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, game, rank)
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(recommendations)")}
        if "target_date" not in columns:
            self.conn.execute("ALTER TABLE recommendations ADD COLUMN target_date TEXT")
        if "target_date_source" not in columns:
            self.conn.execute("ALTER TABLE recommendations ADD COLUMN target_date_source TEXT")
        self.conn.commit()

    def upsert_draws(self, draws: list[Draw]) -> int:
        if not draws:
            return 0
        rows = [
            (
                d.game, d.issue, d.draw_date,
                json.dumps(d.numbers, ensure_ascii=False),
                json.dumps(d.extra, ensure_ascii=False),
                d.sales, d.pool,
                json.dumps(d.raw, ensure_ascii=False, default=str),
            )
            for d in draws
        ]
        self.conn.executemany(
            """INSERT INTO draws(game, issue, draw_date, numbers, extra, sales, pool, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(game, issue) DO UPDATE SET
                 draw_date=excluded.draw_date,
                 numbers=excluded.numbers,
                 extra=excluded.extra,
                 sales=excluded.sales,
                 pool=excluded.pool,
                 raw=excluded.raw""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def count_draws(self, game: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM draws WHERE game=?", (game,)).fetchone()
        return int(row["n"])

    def get_draws(self, game: str, limit: int | None = None) -> list[Draw]:
        sql = "SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC"
        params: list = [game]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        out = [
            Draw(
                game=r["game"], issue=r["issue"], draw_date=r["draw_date"],
                numbers=json.loads(r["numbers"]), extra=json.loads(r["extra"]),
                sales=r["sales"], pool=r["pool"],
            )
            for r in rows
        ]
        out.reverse()  # 旧 -> 新
        return out

    def latest(self, game: str) -> Draw | None:
        draws = self.get_draws(game, limit=1)
        return draws[-1] if draws else None

    def save_recommendations(self, run_id: str, created_at: str,
                             recs: list[GameRecommendation]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, created_at, summary) VALUES (?, ?, ?)",
            (run_id, created_at, json.dumps({"games": [r.game for r in recs]}, ensure_ascii=False)),
        )
        for rec in recs:
            for i, s in enumerate(rec.sets, 1):
                self.conn.execute(
                    """INSERT OR REPLACE INTO recommendations
                       (run_id, game, target_issue, rank, numbers, extra, score, rationale,
                        target_date, target_date_source, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, rec.game, rec.target_issue, i,
                     json.dumps(s.numbers), json.dumps(s.extra),
                     round(s.score, 2), s.rationale,
                     rec.target_date, rec.target_date_source, created_at),
                )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
