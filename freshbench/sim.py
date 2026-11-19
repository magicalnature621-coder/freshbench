"""Simulation mode: an offline, deterministic stand-in for Bifrost + Tavily.

It drives the *real* agent / detector / runner code against a small FICTIONAL world
(data/sim_tasks.json), so the whole pipeline can be tested and demoed without API keys.
Results from simulation mode are labelled "simulation" everywhere and are not real benchmark numbers.
"""
from __future__ import annotations

import json
import re
import zlib

from .config import DATA_DIR
from .gateway import LLMResult, estimate_cost
from .search import Evidence, SearchResult


def _world() -> list[dict]:
    return json.loads((DATA_DIR / "sim_tasks.json").read_text())["tasks"]


def _find(text: str) -> dict | None:
    t = text.lower()
    for e in _world():
        if any(k in t for k in e["keywords"]):
            return e
    return None


def _field(prompt: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*?)(?:\n[A-Z ]+:|\Z)", prompt, re.S | re.M)
    return m.group(1).strip() if m else ""


def _knows_current(model: str, entry: dict) -> bool:
    """Which fictional facts each fictional model 'learned' before its training cut-off."""
    if entry.get("evergreen"):
        return True
    if model.endswith("newer-70b"):
        return zlib.crc32(entry["id"].encode()) % 2 == 0  # newer model knows about half the changes
    return False


class SimGateway:
    def __init__(self, today: str):
        self.today = today

    def health(self) -> bool:
        return True

    def chat(self, model: str, messages: list[dict], *, temperature: float = 0.0, max_tokens: int = 700,
             purpose: str = "") -> LLMResult:
        prompt = messages[-1]["content"]
        content = self._respond(model, prompt, purpose)
        pt = sum(len(m["content"]) for m in messages) // 4
        ct = len(content) // 4
        slow = 3.0 if model.endswith("70b") else 1.0
        return LLMResult(content=content, model=model, provider_used="sim", model_used=model.split("/", 1)[-1],
                         prompt_tokens=pt, completion_tokens=ct, latency_s=round((0.15 + ct * 0.004) * slow, 3),
                         gateway_latency_ms=0.3, upstream_latency_ms=None, fallback_used=False,
                         cost_usd=estimate_cost(model, pt, ct), purpose=purpose)

    def _respond(self, model: str, prompt: str, purpose: str) -> str:
        if purpose in ("agent:closed_book", "agent:guarded_draft"):
            e = _find(prompt)
            if not e:
                return "I'm not sure."
            return e["template"].format(v=e["new"] if _knows_current(model, e) else e["old"])

        if purpose == "agent:search_rag":
            e = _find(prompt.split("QUESTION:")[-1])
            if e and e["new"] in prompt:
                return e["template"].format(v=e["new"]) + " [1]"
            return "The search results do not contain the answer."

        if purpose == "extract_claims":
            q, a = _field(prompt, "QUESTION"), _field(prompt, "ANSWER")
            e = _find(q + " " + a)
            claim = re.sub(r"\s*\[\d+\]|\s*\(source:.*?\)|\s*\(as of .*?\)", "", a).strip()
            if not e:
                return json.dumps({"claims": [{"claim": claim, "time_sensitive": True, "volatility": "medium",
                                               "search_query": q, "topic": "general"}]})
            return json.dumps({"claims": [{"claim": claim, "time_sensitive": not e.get("evergreen", False),
                                           "volatility": e["volatility"], "search_query": e["query"],
                                           "topic": e["topic"]}]})

        if purpose == "verify_claim":
            claim = _field(prompt, "CLAIM")
            e = _find(claim)
            if not e or "(no results)" in prompt:
                return json.dumps({"verdict": "unverifiable", "confidence": 0.3, "current_truth": None,
                                   "explanation": "No relevant evidence found.", "evidence_urls": []})
            url = f"https://sim.freshbench.local/{e['id']}"
            truth = e["template"].format(v=e["new"])
            if e["new"] in claim:
                v, expl = "fresh", "The newest evidence confirms this."
            elif e["old"] in claim:
                v, expl = "stale", f"This was true before {e['changed']}; newer evidence supersedes it."
            else:
                v, expl = "incorrect", "The evidence contradicts this claim."
            return json.dumps({"verdict": v, "confidence": 0.9, "current_truth": truth, "explanation": expl,
                               "evidence_urls": [url], "evidence_date": e["changed"]})

        if purpose == "repair":
            e = _find(_field(prompt, "QUESTION"))
            if e:
                return (e["template"].format(v=e["new"]) +
                        f" (source: https://sim.freshbench.local/{e['id']}) (as of {self.today})")
            return _field(prompt, "ANSWER")
        return "OK"


class SimSearch:
    def __init__(self, today: str):
        self.today = today

    def search(self, query: str, topic: str = "general") -> SearchResult:
        e = _find(query)
        results = []
        if e:
            results.append(Evidence(
                title=f"[SIMULATED] {e['query']}", url=f"https://sim.freshbench.local/{e['id']}",
                content=e["template"].format(v=e["new"]) + f" (updated {e['changed']})",
                published_date=e["changed"], score=0.9))
        return SearchResult(query=query, answer=None, results=results, credits=2, latency_s=0.4)
