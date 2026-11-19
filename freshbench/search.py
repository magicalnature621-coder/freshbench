"""Tavily search: FreshBench's source of *current* truth.

The stale-answer detector turns every time-sensitive claim into a neutral web query and asks
Tavily for fresh evidence (with publish dates). The search-augmented agents use Tavily too.
Results are cached on disk for a few hours so several agents asking the same thing in one
benchmark run don't burn extra credits.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

from .config import CACHE_DIR


@dataclass
class Evidence:
    title: str
    url: str
    content: str
    published_date: str | None = None
    score: float | None = None


@dataclass
class SearchResult:
    query: str
    answer: str | None
    results: list[Evidence] = field(default_factory=list)
    credits: int = 0
    latency_s: float = 0.0
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def as_context(self, max_chars: int = 700) -> str:
        lines = []
        for i, e in enumerate(self.results, 1):
            date = f" (published {e.published_date})" if e.published_date else ""
            lines.append(f"[{i}] {e.title}{date}\nURL: {e.url}\n{e.content[:max_chars]}")
        if self.answer:
            lines.append(f"[Tavily summary] {self.answer}")
        return "\n\n".join(lines) or "(no results)"


class TavilySearch:
    def __init__(self, api_key: str, depth: str = "advanced", max_results: int = 5, cache_ttl_s: int = 6 * 3600):
        if not api_key:
            raise ValueError("TAVILY_API_KEY is not set (get a free key at https://app.tavily.com)")
        from tavily import TavilyClient

        self.client = TavilyClient(api_key=api_key)
        self.depth = depth
        self.max_results = max_results
        self.cache_ttl_s = cache_ttl_s
        self.cache_dir = CACHE_DIR / "tavily"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str):
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")

    def search(self, query: str, topic: str = "general") -> SearchResult:
        topic = topic if topic in ("general", "news", "finance") else "general"
        key = json.dumps([query.lower().strip(), topic, self.depth, self.max_results])
        p = self._cache_path(key)
        if p.exists() and time.time() - p.stat().st_mtime < self.cache_ttl_s:
            d = json.loads(p.read_text())
            d["results"] = [Evidence(**e) for e in d["results"]]
            d["cached"], d["credits"] = True, 0
            return SearchResult(**d)

        t0 = time.perf_counter()
        kwargs = dict(query=query, search_depth=self.depth, max_results=self.max_results, include_answer=True, topic=topic)
        if topic == "news":
            kwargs["days"] = 365
        resp = self.client.search(**kwargs)
        res = SearchResult(
            query=query,
            answer=resp.get("answer"),
            results=[Evidence(title=r.get("title", ""), url=r.get("url", ""), content=r.get("content", ""),
                              published_date=r.get("published_date"), score=r.get("score"))
                     for r in resp.get("results", [])],
            credits=2 if self.depth == "advanced" else 1,
            latency_s=round(time.perf_counter() - t0, 3),
        )
        p.write_text(json.dumps(res.to_dict()))
        return res
