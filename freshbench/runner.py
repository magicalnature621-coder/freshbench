"""Benchmark runner: agents x models x tasks, judged by one fixed Stale-Answer Detector."""
from __future__ import annotations

import json
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

from .agents import AGENTS
from .config import DATA_DIR, Settings, settings as load_settings
from .detector import StaleAnswerDetector
from .store import Store


def load_tasks(path=None, simulate: bool = False) -> list[dict]:
    path = path or DATA_DIR / ("sim_tasks.json" if simulate else "tasks.json")
    return json.loads(open(path).read())["tasks"]


def build_backends(s: Settings, fallbacks: list[str] | None = None):
    """Return (gateway, search). Real mode: Bifrost + Tavily. Simulation mode: offline fakes."""
    if s.simulate:
        from .sim import SimGateway, SimSearch

        return SimGateway(today=s.today), SimSearch(today=s.today)
    from .gateway import BifrostGateway
    from .search import TavilySearch

    return (BifrostGateway(s.bifrost_url, s.bifrost_virtual_key, fallbacks=fallbacks or []),
            TavilySearch(s.tavily_api_key))


def run_one(task: dict, agent_name: str, model: str, gw, search, judge: StaleAnswerDetector, today: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    base = {"task_id": task["id"], "category": task.get("category", ""), "volatility": task.get("volatility", ""),
            "question": task["question"], "agent": agent_name, "model": model, "created_at": now}
    try:
        agent = AGENTS[agent_name](gw, search, today)
        out = agent.run(task["question"], model)
        rep = judge.check(task["question"], out.answer, repair=False)
        c = rep.counts
        gl = [x.gateway_latency_ms if x.gateway_latency_ms is not None else x.upstream_latency_ms for x in out.llm_calls]
        gl = [v for v in gl if v is not None]
        return {**base, "answer": out.answer, "verdict": rep.verdict, "freshness_score": rep.freshness_score,
                "n_fresh": c["fresh"], "n_stale": c["stale"], "n_incorrect": c["incorrect"],
                "n_unverifiable": c["unverifiable"], "n_evergreen": c["evergreen"],
                "prompt_tokens": sum(x.prompt_tokens for x in out.llm_calls),
                "completion_tokens": sum(x.completion_tokens for x in out.llm_calls),
                "llm_cost_usd": out.llm_cost, "tavily_credits": out.tavily_credits, "cost_usd": out.cost_usd,
                "latency_s": out.latency_s, "gateway_latency_ms": sum(gl) if gl else None,
                "fallbacks": out.fallbacks,
                "providers_used": ",".join(sorted({f"{x.provider_used}/{x.model_used}" for x in out.llm_calls})),
                "judge_cost_usd": rep.cost_usd, "judge_credits": rep.tavily_credits, "error": None,
                "detail": {"sources": out.sources, "trace": out.trace, "judge": rep.to_dict()}}
    except Exception as e:  # an agent failing is a benchmark result too (reliability)
        return {**base, "answer": "", "verdict": "error", "freshness_score": None, "n_fresh": 0, "n_stale": 0,
                "n_incorrect": 0, "n_unverifiable": 0, "n_evergreen": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "llm_cost_usd": 0.0, "tavily_credits": 0, "cost_usd": 0.0, "latency_s": None,
                "gateway_latency_ms": None, "fallbacks": 0, "providers_used": "", "judge_cost_usd": 0.0,
                "judge_credits": 0, "error": f"{type(e).__name__}: {e}",
                "detail": {"traceback": traceback.format_exc()[-2000:]}}


def run_benchmark(agents: list[str], models: list[str], tasks: list[dict] | None = None, limit: int | None = None,
                  workers: int = 2, s: Settings | None = None, fallbacks: list[str] | None = None,
                  progress: Callable[[int, int, dict], None] | None = None, notes: str = "") -> str:
    s = s or load_settings()
    tasks = tasks if tasks is not None else load_tasks(simulate=s.simulate)
    if limit:
        tasks = tasks[:limit]
    unknown = [a for a in agents if a not in AGENTS]
    if unknown:
        raise ValueError(f"unknown agents {unknown}; choose from {list(AGENTS)}")
    gw, search = build_backends(s, fallbacks)
    judge = StaleAnswerDetector(gw, search, judge_model=s.judge_model, today=s.today)
    store = Store(s.db_path)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    store.create_run({"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
                      "mode": "simulation" if s.simulate else "live", "judge_model": s.judge_model, "today": s.today,
                      "agents": agents, "models": models, "n_tasks": len(tasks), "notes": notes})
    jobs = [(t, a, m) for t in tasks for a in agents for m in models]
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(run_one, t, a, m, gw, search, judge, s.today) for t, a, m in jobs]
        for f in as_completed(futs):
            row = f.result()
            store.add_result({"run_id": run_id, **row})
            done += 1
            if progress:
                progress(done, len(jobs), row)
    return run_id
