"""FreshBench CLI.

  python -m freshbench doctor                         # check Bifrost + Tavily + keys
  python -m freshbench bifrost-config                 # write bifrost/config.json from .env
  python -m freshbench check "question" "answer"      # run the Stale-Answer Detector on one answer
  python -m freshbench run --agents closed_book search_rag guarded --models groq/llama-3.1-8b-instant --limit 10
  python -m freshbench leaderboard [run_id]
  python -m freshbench calibrate                      # detector precision/recall on labelled stale/evergreen answers
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import DATA_DIR, available_models, settings


def _print_report(rep) -> None:
    icon = {"fresh": "✅", "stale": "🕰️ ", "incorrect": "❌", "unverifiable": "❔", "evergreen": "🌲"}
    print(f"\nVERDICT: {rep.verdict.upper()}   freshness={rep.freshness_score}   judge={rep.judge_model}")
    for c in rep.claims:
        print(f"  {icon.get(c.verdict, '•')} [{c.verdict}] {c.claim}")
        if c.current_truth and c.verdict != "fresh":
            print(f"       now: {c.current_truth}")
        for u in c.evidence_urls[:2]:
            print(f"       src: {u}")
    if rep.corrected_answer:
        print(f"\nCORRECTED: {rep.corrected_answer}")
    print(f"\ncost=${rep.cost_usd:.5f}  tavily_credits={rep.tavily_credits}  latency={rep.latency_s}s")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="freshbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("bifrost-config")
    c = sub.add_parser("check")
    c.add_argument("question")
    c.add_argument("answer")
    c.add_argument("--no-repair", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--agents", nargs="+", default=["closed_book", "search_rag", "guarded"])
    r.add_argument("--models", nargs="+", default=None)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--fallbacks", nargs="*", default=[], help="Bifrost fallback models, e.g. gemini/gemini-2.5-flash")
    r.add_argument("--notes", default="")
    lb = sub.add_parser("leaderboard")
    lb.add_argument("run_id", nargs="?")
    sub.add_parser("calibrate")
    a = p.parse_args(argv)
    s = settings()

    if a.cmd == "bifrost-config":
        from .bifrost_config import write_config

        print(f"wrote {write_config()}")
        return 0

    if a.cmd == "doctor":
        from .runner import build_backends

        print(f"mode: {'SIMULATION' if s.simulate else 'live'} | today={s.today} | judge={s.judge_model}")
        print(f"models available: {available_models() or 'none - add provider keys to .env'}")
        print(f"tavily key: {'set' if s.tavily_api_key else 'MISSING'}")
        try:
            gw, _ = build_backends(s)
            print(f"bifrost {s.bifrost_url}: {'OK' if gw.health() else 'NOT REACHABLE (docker compose up -d)'}")
        except Exception as e:
            print(f"backend error: {e}")
        return 0

    from .runner import build_backends, run_benchmark
    from .store import Store

    if a.cmd == "check":
        from .detector import StaleAnswerDetector

        gw, search = build_backends(s)
        rep = StaleAnswerDetector(gw, search, s.judge_model, s.today).check(a.question, a.answer, repair=not a.no_repair)
        _print_report(rep)
        return 0

    if a.cmd == "run":
        models = a.models or available_models()
        if not models:
            print("No models: add provider keys to .env or pass --models")
            return 1
        print(f"Running {a.agents} x {models} ({'SIMULATION' if s.simulate else 'live'})")

        def prog(done, total, row):
            print(f"  [{done}/{total}] {row['agent']:<12} {row['model']:<34} {row['task_id']}  -> {row['verdict']}"
                  + (f"  ({row['error'][:80]})" if row.get("error") else ""))

        run_id = run_benchmark(a.agents, models, limit=a.limit, workers=a.workers, s=s, fallbacks=a.fallbacks,
                               progress=prog, notes=a.notes)
        a.run_id = run_id
        a.cmd = "leaderboard"

    if a.cmd == "leaderboard":
        from .metrics import leaderboard

        st = Store(s.db_path)
        runs = st.runs()
        if not runs:
            print("no runs yet")
            return 1
        rid = a.run_id or runs[0]["run_id"]
        df = leaderboard(st.results(rid))
        import pandas as pd

        with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.4f}".format):
            print(f"\nLeaderboard for run {rid}")
            print(df[["agent", "model", "fresh_score", "fresh_rate", "stale_rate", "avg_cost_usd",
                      "cost_per_fresh_answer", "avg_latency_s", "avg_tokens", "fallbacks", "error_rate"]].to_string())
        return 0

    if a.cmd == "calibrate":
        from .detector import StaleAnswerDetector

        if s.simulate:
            print("calibrate needs live mode (real web evidence)")
            return 1
        gw, search = build_backends(s)
        det = StaleAnswerDetector(gw, search, s.judge_model, s.today)
        items = json.loads((DATA_DIR / "calibration.json").read_text())["items"]
        tp = fp = fn = tn = 0
        for it in items:
            rep = det.check(it["question"], it["answer"], repair=False)
            flagged = rep.verdict in ("stale", "incorrect")
            truth = it["label"] == "stale"
            tp += flagged and truth
            fp += flagged and not truth
            fn += (not flagged) and truth
            tn += (not flagged) and not truth
            print(f"  {'OK ' if flagged == truth else 'MISS'} label={it['label']:<9} verdict={rep.verdict:<18} {it['answer']}")
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        print(f"\nstale-detection precision={prec:.2f} recall={rec:.2f} accuracy={(tp + tn) / len(items):.2f}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
