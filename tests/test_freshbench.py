import json
import os

import pytest

os.environ["FRESHBENCH_SIMULATE"] = "1"

from freshbench.bifrost_config import build_config  # noqa: E402
from freshbench.config import Settings  # noqa: E402
from freshbench.detector import ClaimCheck, StaleAnswerDetector, aggregate  # noqa: E402
from freshbench.gateway import estimate_cost, parse_json  # noqa: E402
from freshbench.metrics import leaderboard  # noqa: E402
from freshbench.runner import run_benchmark  # noqa: E402
from freshbench.sim import SimGateway, SimSearch  # noqa: E402
from freshbench.store import Store  # noqa: E402


def test_parse_json_variants():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json('Sure! Here it is: {"a": 3} hope that helps') == {"a": 3}
    with pytest.raises(ValueError):
        parse_json("no json here")


def _c(v, ts=True):
    return ClaimCheck(claim="x", time_sensitive=ts, verdict=v if ts else "evergreen")


@pytest.mark.parametrize("verdicts,expected,score", [
    (["fresh", "fresh"], "fresh", 1.0),
    (["fresh", "stale"], "stale", 0.5),
    (["incorrect"], "incorrect", 0.0),
    (["fresh", "unverifiable"], "partially_verified", 1.0),
    (["unverifiable"], "unverifiable", None),
])
def test_aggregate(verdicts, expected, score):
    assert aggregate([_c(v) for v in verdicts]) == (expected, score)


def test_aggregate_evergreen():
    assert aggregate([_c("x", ts=False)]) == ("evergreen", None)


def test_detector_flags_and_repairs_stale_answer():
    det = StaleAnswerDetector(SimGateway("2026-11-19"), SimSearch("2026-11-19"), "sim/newer-70b", "2026-11-19")
    rep = det.check("Who is the current CEO of Acme Robotics?", "The current CEO of Acme Robotics is Dana Whitfield.")
    assert rep.verdict == "stale"
    assert "Priya Raman" in rep.corrected_answer
    assert rep.tavily_credits == 2 and len(rep.llm_calls) == 3


def test_detector_fresh_and_evergreen():
    det = StaleAnswerDetector(SimGateway("2026-11-19"), SimSearch("2026-11-19"), "sim/newer-70b", "2026-11-19")
    assert det.check("Newest Orion AI Labs model?", "The newest model released by Orion AI Labs is Orion-4.5.").verdict == "fresh"
    ev = det.check("Who founded Halcyon Devices?", "Halcyon Devices was founded by Ines Carvalho.")
    assert ev.verdict == "evergreen" and ev.tavily_credits == 0


def test_full_benchmark_simulation(tmp_path):
    s = Settings()
    s.db_path = tmp_path / "t.db"
    rid = run_benchmark(["closed_book", "search_rag", "guarded"], ["sim/oldie-8b", "sim/newer-70b"], s=s, workers=3)
    rows = Store(s.db_path).results(rid)
    assert len(rows) == 8 * 3 * 2
    assert not [r for r in rows if r["error"]]
    lb = leaderboard(rows).set_index(["agent", "model"])
    # an old closed-book model is always stale on volatile facts; grounded agents fix that
    assert lb.loc[("closed_book", "sim/oldie-8b"), "stale_rate"] == 1.0
    assert lb.loc[("search_rag", "sim/oldie-8b"), "fresh_rate"] == 1.0
    assert lb.loc[("guarded", "sim/oldie-8b"), "fresh_rate"] == 1.0


def test_bifrost_config_only_includes_providers_with_keys():
    cfg = build_config(env={"GROQ_API_KEY": "x", "BIFROST_VIRTUAL_KEY": "sk-bf-t"})
    assert set(cfg["providers"]) == {"groq"}
    assert cfg["providers"]["groq"]["keys"][0]["value"] == "env.GROQ_API_KEY"  # key never written to disk
    vk = cfg["governance"]["virtual_keys"][0]
    assert vk["value"] == "sk-bf-t" and vk["provider_configs"][0]["allow_all_keys"] is True
    json.dumps(cfg)


def test_cost_estimate():
    assert estimate_cost("openai/gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    assert estimate_cost("unknown/model", 100, 100) == 0.0
