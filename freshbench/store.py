"""SQLite persistence for benchmark runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, created_at TEXT, mode TEXT, judge_model TEXT, today TEXT,
    agents TEXT, models TEXT, n_tasks INTEGER, notes TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, task_id TEXT, category TEXT, volatility TEXT, question TEXT,
    agent TEXT, model TEXT, answer TEXT,
    verdict TEXT, freshness_score REAL,
    n_fresh INTEGER, n_stale INTEGER, n_incorrect INTEGER, n_unverifiable INTEGER, n_evergreen INTEGER,
    prompt_tokens INTEGER, completion_tokens INTEGER, llm_cost_usd REAL, tavily_credits INTEGER, cost_usd REAL,
    latency_s REAL, gateway_latency_ms REAL, fallbacks INTEGER, providers_used TEXT,
    judge_cost_usd REAL, judge_credits INTEGER,
    error TEXT, detail TEXT, created_at TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30)

    def create_run(self, run: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO runs VALUES (:run_id,:created_at,:mode,:judge_model,:today,:agents,:models,:n_tasks,:notes)",
                      {**run, "agents": json.dumps(run["agents"]), "models": json.dumps(run["models"])})

    def add_result(self, row: dict) -> None:
        row = {**row, "detail": json.dumps(row.get("detail") or {}, default=str)}
        cols = ",".join(row)
        with self._conn() as c:
            c.execute(f"INSERT INTO results ({cols}) VALUES ({','.join(':' + k for k in row)})", row)

    def runs(self) -> list[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def results(self, run_id: str) -> list[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM results WHERE run_id=? ORDER BY id", (run_id,))]
