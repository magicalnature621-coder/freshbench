"""Bifrost gateway client.

Every LLM call in FreshBench (agents *and* the stale-answer judge) goes through Bifrost's
OpenAI-compatible endpoint. Bifrost gives us, for free:
  * one API for OpenAI / Anthropic / Gemini / Groq / ... ("provider/model" ids)
  * governance through a virtual key (x-bf-vk header): which providers/models FreshBench may use
  * automatic fallbacks to other models when a provider fails
  * per-request telemetry: provider actually used, resolved model, gateway + upstream latency, token usage
FreshBench records all of that per agent run, which is what turns a model benchmark into an
*agent* benchmark (cost, latency, reliability, not just accuracy).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass

import requests

from .config import model_price


class GatewayError(RuntimeError):
    pass


@dataclass
class LLMResult:
    content: str
    model: str  # requested "provider/model"
    provider_used: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float  # wall-clock, client side
    gateway_latency_ms: float | None  # reported by Bifrost
    upstream_latency_ms: float | None  # provider time, reported by Bifrost
    fallback_used: bool
    cost_usd: float
    purpose: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = model_price(model)
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


class BifrostGateway:
    """Thin client for Bifrost's OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, base_url: str, virtual_key: str = "", fallbacks: list[str] | None = None,
                 timeout: float = 120, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.virtual_key = virtual_key
        self.fallbacks = fallbacks or []
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def health(self) -> bool:
        try:
            return self.session.get(f"{self.base_url}/health", timeout=5).ok
        except requests.RequestException:
            return False

    def chat(self, model: str, messages: list[dict], *, temperature: float = 0.0, max_tokens: int = 700,
             purpose: str = "") -> LLMResult:
        body: dict = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        fallbacks = [m for m in self.fallbacks if m != model]
        if fallbacks:
            body["fallbacks"] = fallbacks  # Bifrost tries these in order if the primary fails
        headers = {"Content-Type": "application/json"}
        if self.virtual_key:
            headers["x-bf-vk"] = self.virtual_key

        last_err = ""
        for attempt in range(self.max_retries):
            t0 = time.perf_counter()
            try:
                r = self.session.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers,
                                      timeout=self.timeout)
            except requests.RequestException as e:
                last_err = f"cannot reach Bifrost at {self.base_url}: {e}"
                time.sleep(1.5 * (attempt + 1))
                continue
            wall = time.perf_counter() - t0
            if r.status_code == 200:
                return self._parse(model, r, wall, purpose)
            last_err = f"Bifrost HTTP {r.status_code}: {r.text[:400]}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2.0 * (attempt + 1))
                continue
            break  # 4xx config errors: retrying will not help
        raise GatewayError(last_err)

    @staticmethod
    def _parse(model: str, r: requests.Response, wall: float, purpose: str) -> LLMResult:
        data = r.json()
        h = r.headers
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        extra = data.get("extra_fields") or {}
        routing = extra.get("routing_info") or {}
        provider_used = h.get("x-bifrost-provider") or extra.get("provider") or model.split("/")[0]
        model_used = h.get("x-bifrost-resolved-model") or extra.get("resolved_model_used") or model.split("/", 1)[-1]
        fb_idx = h.get("x-bifrost-fallback-index")
        fallback_used = bool(
            (fb_idx not in (None, "", "0"))
            or str(h.get("x-bifrost-routing-info-is-fallback", "")).lower() == "true"
            or routing.get("is_fallback")
        )
        used_id = f"{provider_used}/{model_used}"
        cost = None
        for c in (usage.get("cost"), extra.get("cost")):  # prefer cost computed by Bifrost when present
            if isinstance(c, dict):
                c = c.get("total_cost")
            if _float(c):
                cost = float(c)
                break
        if cost is None:
            cost = estimate_cost(used_id, pt, ct)
        return LLMResult(
            content=content.strip(), model=model, provider_used=provider_used, model_used=model_used,
            prompt_tokens=pt, completion_tokens=ct, latency_s=round(wall, 3),
            gateway_latency_ms=_float(h.get("x-bifrost-latency-ms")),
            upstream_latency_ms=_float(h.get("x-bifrost-upstream-latency-ms")),
            fallback_used=fallback_used, cost_usd=cost, purpose=purpose,
        )


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict:
    """Robustly pull a JSON object out of an LLM reply (handles ```json fences and chatter)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"model did not return JSON: {text[:200]!r}")
