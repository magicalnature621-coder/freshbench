"""Stale-Answer Detector.

Pipeline for one (question, answer) pair:
  1. Claim extraction (LLM via Bifrost): split the answer into atomic claims, flag which ones are
     *time-sensitive* (office holders, latest versions, prices, rankings, "most recent" events...),
     and write a neutral search query for each that reveals the CURRENT truth without presupposing
     the claimed value.
  2. Evidence (Tavily): search each time-sensitive claim, keeping URLs and publish dates.
  3. Verification (LLM via Bifrost): judge each claim against the dated evidence:
        fresh        - evidence confirms it is true today
        stale        - it used to be true (or was true at some cut-off) but newer evidence supersedes it
        incorrect    - contradicted by evidence and never was the current truth
        unverifiable - evidence is insufficient
  4. Repair (optional): rewrite the answer so it is current, with citations and an "as of" date.

The answer-level verdict is `stale` if any claim is stale/incorrect, `fresh` if all time-sensitive
claims are verified fresh, `evergreen` if nothing in it can go stale, and otherwise
`partially_verified` / `unverifiable`.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .gateway import LLMResult, parse_json
from .search import SearchResult

EXTRACT_PROMPT = """Today's date is {today}. You audit AI answers for STALENESS (facts that may have changed since a model was trained).

Break the ANSWER into at most {max_claims} atomic factual claims that answer the QUESTION.
For each claim decide:
- time_sensitive: true if its truth can change over time (current office holders/CEOs, "latest"/"newest" versions or products, prices, rates, rankings, records, champions/"most recent" winners, statistics, ongoing events). Evergreen facts (history with a fixed date, definitions, science, geography) are false.
- volatility: "high" (changes within months), "medium" (within a few years) or "low".
- search_query: a NEUTRAL web search query that reveals the CURRENT truth WITHOUT presupposing the claimed value. Example: for "Rishi Sunak is the UK prime minister" use "current UK prime minister {year}", never "Rishi Sunak prime minister".
- topic: "news" for events/people/politics/sports, "finance" for prices/rates/markets, otherwise "general".

Return ONLY JSON, no prose:
{{"claims": [{{"claim": "...", "time_sensitive": true, "volatility": "high", "search_query": "...", "topic": "general"}}]}}

QUESTION: {question}
ANSWER: {answer}"""

VERIFY_PROMPT = """Today's date is {today}. Decide whether the CLAIM is true *today*, using ONLY the dated web EVIDENCE below (ignore your own memory - it may be outdated).

Verdicts:
- "fresh": the evidence confirms the claim is currently true.
- "stale": the claim was true at some earlier point, but newer evidence shows the world has moved on (e.g. a former office holder, an older version, a previous champion, an old price).
- "incorrect": the evidence contradicts the claim and it does not look like it was ever the current truth.
- "unverifiable": the evidence is missing, irrelevant or too old to decide.
Prefer the most recently published evidence when sources disagree. Be strict: "fresh" requires explicit support.

Return ONLY JSON:
{{"verdict": "fresh|stale|incorrect|unverifiable", "confidence": 0.0-1.0, "current_truth": "what is true today according to the evidence, or null", "explanation": "one sentence", "evidence_urls": ["urls you relied on"], "evidence_date": "YYYY-MM-DD of the newest relevant evidence, or null"}}

CLAIM: {claim}

EVIDENCE:
{evidence}"""

REPAIR_PROMPT = """Today's date is {today}. The ANSWER below to the QUESTION contains outdated or wrong claims. Rewrite it so it is correct TODAY, using only the verified facts listed. Keep it concise (1-3 sentences), keep correct parts, cite sources inline as (source: URL), and end with "(as of {today})". Return only the rewritten answer.

QUESTION: {question}
ANSWER: {answer}

VERIFIED FACTS:
{facts}"""

VERDICTS = ("fresh", "stale", "incorrect", "unverifiable")


@dataclass
class ClaimCheck:
    claim: str
    time_sensitive: bool
    volatility: str = "medium"
    search_query: str = ""
    topic: str = "general"
    verdict: str = "evergreen"  # evergreen claims are not searched
    confidence: float | None = None
    current_truth: str | None = None
    explanation: str = ""
    evidence_urls: list[str] = field(default_factory=list)
    evidence_date: str | None = None
    search: dict | None = None


@dataclass
class FreshnessReport:
    question: str
    answer: str
    verdict: str
    freshness_score: float | None  # fresh / (fresh + stale + incorrect) over checked claims
    claims: list[ClaimCheck]
    corrected_answer: str | None
    judge_model: str
    llm_calls: list[dict] = field(default_factory=list)
    tavily_credits: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        c = {v: 0 for v in (*VERDICTS, "evergreen")}
        for cl in self.claims:
            c[cl.verdict] = c.get(cl.verdict, 0) + 1
        return c

    def to_dict(self) -> dict:
        d = asdict(self)
        d["counts"] = self.counts
        return d


def aggregate(claims: list[ClaimCheck]) -> tuple[str, float | None]:
    ts = [c for c in claims if c.time_sensitive]
    if not claims:
        return "unverifiable", None
    if not ts:
        return "evergreen", None
    bad = sum(c.verdict in ("stale", "incorrect") for c in ts)
    fresh = sum(c.verdict == "fresh" for c in ts)
    decided = fresh + bad
    score = round(fresh / decided, 3) if decided else None
    if any(c.verdict == "stale" for c in ts):
        return "stale", score
    if bad:
        return "incorrect", score
    if fresh == len(ts):
        return "fresh", score
    if fresh:
        return "partially_verified", score
    return "unverifiable", score


class StaleAnswerDetector:
    def __init__(self, gateway, search, judge_model: str, today: str, max_claims: int = 4):
        self.gw = gateway
        self.search = search
        self.judge_model = judge_model
        self.today = today
        self.max_claims = max_claims

    def _llm(self, prompt: str, purpose: str, calls: list[LLMResult], max_tokens: int = 600) -> LLMResult:
        res = self.gw.chat(self.judge_model, [{"role": "user", "content": prompt}], max_tokens=max_tokens,
                           purpose=purpose)
        calls.append(res)
        return res

    def extract_claims(self, question: str, answer: str, calls: list[LLMResult]) -> list[ClaimCheck]:
        prompt = EXTRACT_PROMPT.format(today=self.today, year=self.today[:4], max_claims=self.max_claims,
                                       question=question, answer=answer)
        res = self._llm(prompt, "extract_claims", calls)
        try:
            raw = parse_json(res.content).get("claims", [])
        except ValueError:
            # Fall back to treating the whole answer as one time-sensitive claim.
            raw = [{"claim": answer, "time_sensitive": True, "search_query": question}]
        claims = []
        for c in raw[: self.max_claims]:
            if not isinstance(c, dict) or not str(c.get("claim", "")).strip():
                continue
            ts = c.get("time_sensitive")
            ts = ts if isinstance(ts, bool) else str(ts).lower() == "true"
            claims.append(ClaimCheck(
                claim=str(c["claim"]).strip(), time_sensitive=ts,
                volatility=str(c.get("volatility") or "medium"),
                search_query=str(c.get("search_query") or question),
                topic=str(c.get("topic") or "general"),
                verdict="unverifiable" if ts else "evergreen",
            ))
        return claims

    def verify_claim(self, claim: ClaimCheck, calls: list[LLMResult]) -> SearchResult:
        sr = self.search.search(claim.search_query, topic=claim.topic)
        claim.search = {"query": sr.query, "answer": sr.answer, "cached": sr.cached,
                        "results": [{"title": e.title, "url": e.url, "published_date": e.published_date}
                                    for e in sr.results]}
        prompt = VERIFY_PROMPT.format(today=self.today, claim=claim.claim, evidence=sr.as_context())
        res = self._llm(prompt, "verify_claim", calls, max_tokens=400)
        try:
            v = parse_json(res.content)
        except ValueError:
            v = {"verdict": "unverifiable", "explanation": "judge returned unparseable output"}
        verdict = str(v.get("verdict", "unverifiable")).lower().strip()
        claim.verdict = verdict if verdict in VERDICTS else "unverifiable"
        try:
            claim.confidence = float(v.get("confidence")) if v.get("confidence") is not None else None
        except (TypeError, ValueError):
            claim.confidence = None
        claim.current_truth = v.get("current_truth") or None
        claim.explanation = str(v.get("explanation") or "")
        claim.evidence_urls = [u for u in (v.get("evidence_urls") or []) if isinstance(u, str)][:4]
        claim.evidence_date = v.get("evidence_date") or None
        return sr

    def repair(self, question: str, answer: str, claims: list[ClaimCheck], calls: list[LLMResult]) -> str:
        facts = []
        for c in claims:
            if c.verdict in ("stale", "incorrect") and c.current_truth:
                facts.append(f"- OUTDATED: \"{c.claim}\" -> CURRENT: {c.current_truth} "
                             f"(source: {c.evidence_urls[0] if c.evidence_urls else 'web search'})")
            elif c.verdict == "fresh":
                facts.append(f"- STILL TRUE: {c.claim}")
        prompt = REPAIR_PROMPT.format(today=self.today, question=question, answer=answer, facts="\n".join(facts))
        return self._llm(prompt, "repair", calls, max_tokens=300).content

    def check(self, question: str, answer: str, repair: bool = True) -> FreshnessReport:
        t0 = time.perf_counter()
        calls: list[LLMResult] = []
        credits = 0
        claims = self.extract_claims(question, answer, calls)
        for c in claims:
            if c.time_sensitive:
                credits += self.verify_claim(c, calls).credits
        verdict, score = aggregate(claims)
        corrected = None
        if repair and verdict in ("stale", "incorrect") and any(c.current_truth for c in claims):
            corrected = self.repair(question, answer, claims, calls)
        return FreshnessReport(
            question=question, answer=answer, verdict=verdict, freshness_score=score, claims=claims,
            corrected_answer=corrected, judge_model=self.judge_model,
            llm_calls=[c.to_dict() for c in calls], tavily_credits=credits,
            cost_usd=sum(c.cost_usd for c in calls), latency_s=round(time.perf_counter() - t0, 3),
        )
