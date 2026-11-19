"""The agents under test.

FreshBench benchmarks *agent designs*, not just models: the same model is run inside different
agent architectures, and every one of them reaches its LLM through Bifrost.

  closed_book  - the model answers from its own memory (training data). Cheap, fast, goes stale.
  search_rag   - one Tavily search on the question, then the model answers from the results.
  guarded      - closed-book draft, then the Stale-Answer Detector audits it and repairs any stale
                 claims with Tavily evidence. Shows the detector used as a drop-in guardrail.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import TAVILY_USD_PER_CREDIT
from .detector import StaleAnswerDetector
from .gateway import LLMResult

CLOSED_BOOK_SYSTEM = "You are a helpful assistant. Answer the question directly and concisely in 1-3 sentences."

SEARCH_SYSTEM = ("You are a research assistant. Today's date is {today}. Answer the question in 1-3 sentences "
                 "using ONLY the search results provided. Prefer the most recently published sources. "
                 "Cite sources inline as [n]. If the results do not contain the answer, say so.")


@dataclass
class AgentOutput:
    answer: str
    llm_calls: list[LLMResult] = field(default_factory=list)
    tavily_credits: int = 0
    sources: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    trace: dict = field(default_factory=dict)

    @property
    def llm_cost(self) -> float:
        return sum(c.cost_usd for c in self.llm_calls)

    @property
    def cost_usd(self) -> float:
        return self.llm_cost + self.tavily_credits * TAVILY_USD_PER_CREDIT

    @property
    def tokens(self) -> int:
        return sum(c.prompt_tokens + c.completion_tokens for c in self.llm_calls)

    @property
    def fallbacks(self) -> int:
        return sum(c.fallback_used for c in self.llm_calls)


class Agent:
    name = "base"
    description = ""

    def __init__(self, gateway, search, today: str):
        self.gw, self.search, self.today = gateway, search, today

    def run(self, question: str, model: str) -> AgentOutput:
        t0 = time.perf_counter()
        out = self._run(question, model)
        wall = time.perf_counter() - t0
        out.latency_s = round(max(wall, sum(c.latency_s for c in out.llm_calls)), 3)
        return out

    def _run(self, question: str, model: str) -> AgentOutput:  # pragma: no cover
        raise NotImplementedError


class ClosedBookAgent(Agent):
    name = "closed_book"
    description = "LLM answers from memory only"

    def _run(self, question, model):
        res = self.gw.chat(model, [{"role": "system", "content": CLOSED_BOOK_SYSTEM},
                                   {"role": "user", "content": question}], purpose="agent:closed_book")
        return AgentOutput(answer=res.content, llm_calls=[res])


class SearchRAGAgent(Agent):
    name = "search_rag"
    description = "Tavily search -> LLM answers from results"

    def _run(self, question, model):
        sr = self.search.search(question, topic="general")
        res = self.gw.chat(model, [
            {"role": "system", "content": SEARCH_SYSTEM.format(today=self.today)},
            {"role": "user", "content": f"SEARCH RESULTS:\n{sr.as_context()}\n\nQUESTION: {question}"},
        ], purpose="agent:search_rag")
        return AgentOutput(answer=res.content, llm_calls=[res], tavily_credits=sr.credits,
                           sources=[e.url for e in sr.results], trace={"search_query": sr.query})


class GuardedAgent(Agent):
    name = "guarded"
    description = "closed-book draft -> Stale-Answer Detector -> auto-repair"

    def _run(self, question, model):
        draft = self.gw.chat(model, [{"role": "system", "content": CLOSED_BOOK_SYSTEM},
                                     {"role": "user", "content": question}], purpose="agent:guarded_draft")
        # The guard runs on the agent's own model, so its cost is charged to the agent.
        guard = StaleAnswerDetector(self.gw, self.search, judge_model=model, today=self.today)
        rep = guard.check(question, draft.content, repair=True)
        calls = [draft]
        # Rebuild LLMResult objects for cost accounting.
        calls += [LLMResult(**c) for c in rep.llm_calls]
        answer = rep.corrected_answer or draft.content
        sources = [u for c in rep.claims for u in c.evidence_urls]
        return AgentOutput(answer=answer, llm_calls=calls, tavily_credits=rep.tavily_credits, sources=sources,
                           trace={"draft": draft.content, "guard_verdict": rep.verdict, "repaired": bool(rep.corrected_answer)})


AGENTS: dict[str, type[Agent]] = {a.name: a for a in (ClosedBookAgent, SearchRAGAgent, GuardedAgent)}
