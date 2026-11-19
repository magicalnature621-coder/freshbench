"""Leaderboard metrics."""
from __future__ import annotations

import pandas as pd


def leaderboard(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = []
    for (agent, model), g in df.groupby(["agent", "model"]):
        ok = g[g["verdict"] != "error"]
        n, n_ok = len(g), len(ok)
        fresh = int((ok["verdict"] == "fresh").sum())
        stale = int(ok["verdict"].isin(["stale", "incorrect"]).sum())
        # Answers with nothing time-sensitive in them (evergreen controls) don't count toward freshness.
        n_ts = n_ok - int((ok["verdict"] == "evergreen").sum())
        total_cost = float(ok["cost_usd"].sum())
        out.append({
            "agent": agent,
            "model": model,
            "tasks": n,
            "fresh_rate": fresh / n_ts if n_ts else 0.0,
            "stale_rate": stale / n_ts if n_ts else 0.0,
            "unverified_rate": (n_ts - fresh - stale) / n_ts if n_ts else 0.0,
            "claim_freshness": ok["freshness_score"].dropna().mean() if n_ok else None,
            "avg_cost_usd": total_cost / n_ok if n_ok else None,
            "cost_per_fresh_answer": total_cost / fresh if fresh else None,
            "avg_latency_s": ok["latency_s"].mean() if n_ok else None,
            "avg_tokens": (ok["prompt_tokens"] + ok["completion_tokens"]).mean() if n_ok else None,
            "fallbacks": int(g["fallbacks"].fillna(0).sum()),
            "error_rate": (n - n_ok) / n,
        })
    lb = pd.DataFrame(out)
    # FreshScore: freshness first, reliability second. 100 = every answer verified current, no errors.
    lb["fresh_score"] = (100 * lb["fresh_rate"] * (1 - lb["error_rate"]) - 50 * lb["stale_rate"]).round(1)
    return lb.sort_values(["fresh_score", "avg_cost_usd"], ascending=[False, True]).reset_index(drop=True)
