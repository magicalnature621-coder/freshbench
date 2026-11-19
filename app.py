"""FreshBench dashboard:  streamlit run app.py"""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from freshbench.agents import AGENTS
from freshbench.config import available_models, settings
from freshbench.detector import StaleAnswerDetector
from freshbench.metrics import leaderboard
from freshbench.runner import build_backends, run_benchmark
from freshbench.store import Store

st.set_page_config(page_title="FreshBench", page_icon="🕰️", layout="wide")
S = settings()

VERDICT_STYLE = {
    "fresh": ("✅", "#16a34a"), "stale": ("🕰️", "#dc2626"), "incorrect": ("❌", "#b91c1c"),
    "unverifiable": ("❔", "#a16207"), "evergreen": ("🌲", "#2563eb"), "partially_verified": ("◐", "#a16207"),
    "error": ("⚠️", "#6b7280"),
}

LIVE_PRESETS = {
    "FIFA World Cup (classic stale answer)": ("Which country won the most recent FIFA World Cup?",
                                               "Argentina won the most recent FIFA World Cup, beating France in the 2022 final."),
    "Latest Python version": ("What is the latest stable version of Python?", "The latest stable version of Python is Python 3.11."),
    "UK Prime Minister": ("Who is the current Prime Minister of the United Kingdom?", "Rishi Sunak is the current Prime Minister of the United Kingdom."),
    "Fed rate": ("What is the current target range for the US federal funds rate?", "The Federal Reserve's target range is 5.25% to 5.50%."),
    "Evergreen control": ("When did Apollo 11 land on the Moon?", "Apollo 11 landed on the Moon on July 20, 1969."),
}
SIM_PRESETS = {
    "Acme Robotics CEO (stale)": ("Who is the current CEO of Acme Robotics?", "The current CEO of Acme Robotics is Dana Whitfield."),
    "Zephyr version (stale)": ("What is the latest stable version of the Zephyr web framework?", "The latest stable version of the Zephyr web framework is 4.2."),
    "Orion AI Labs (fresh)": ("What is the newest model released by Orion AI Labs?", "The newest model released by Orion AI Labs is Orion-4.5."),
    "Harbor Spire (evergreen)": ("In which year was the Harbor Spire in Port Sorell completed?", "The Harbor Spire in Port Sorell was completed in 1987."),
}


@st.cache_resource
def backends(simulate: bool):
    return build_backends(S)


def badge(verdict: str) -> str:
    icon, color = VERDICT_STYLE.get(verdict, ("•", "#6b7280"))
    return (f"<span style='background:{color};color:white;padding:3px 10px;border-radius:12px;"
            f"font-weight:600'>{icon} {verdict.replace('_', ' ').upper()}</span>")


# ---------------- sidebar ----------------
with st.sidebar:
    st.title("🕰️ FreshBench")
    st.caption("Benchmark AI agents on whether their answers are **still true**.")
    if S.simulate:
        st.warning("SIMULATION MODE: fictional world, no API calls. Set FRESHBENCH_SIMULATE=0 for live results.")
    else:
        st.success("LIVE MODE: Bifrost + Tavily")
    try:
        gw, search = backends(S.simulate)
        ok = gw.health()
    except Exception as e:  # missing keys etc.
        gw = search = None
        ok = False
        st.error(str(e))
    st.markdown(f"**Bifrost gateway:** {'🟢 up' if ok else '🔴 down'}  \n`{S.bifrost_url}`")
    st.markdown(f"**Judge model:** `{S.judge_model}`  \n**Today:** {S.today}")
    st.markdown(f"**Models:** {', '.join(f'`{m}`' for m in available_models()) or 'none configured'}")

tab_detect, tab_board, tab_run, tab_how = st.tabs(["🔎 Stale-Answer Detector", "🏆 Leaderboard", "▶️ Run benchmark", "🧭 How it works"])

# ---------------- detector ----------------
with tab_detect:
    st.subheader("Is this AI answer still true today?")
    presets = SIM_PRESETS if S.simulate else LIVE_PRESETS
    choice = st.selectbox("Try an example", ["(custom)"] + list(presets))
    q0, a0 = presets.get(choice, ("", ""))
    q = st.text_input("Question", q0)
    a = st.text_area("AI answer to audit", a0, height=90)
    col1, col2 = st.columns([1, 3])
    repair = col1.checkbox("Auto-repair stale answers", True)
    if col2.button("Check freshness", type="primary", disabled=not (q and a and gw)):
        with st.spinner("Extracting claims → searching Tavily → judging via Bifrost…"):
            rep = StaleAnswerDetector(gw, search, S.judge_model, S.today).check(q, a, repair=repair)
        st.markdown(f"### {badge(rep.verdict)}", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Claim freshness", "n/a" if rep.freshness_score is None else f"{rep.freshness_score:.0%}")
        m2.metric("Cost", f"${rep.cost_usd:.5f}")
        m3.metric("Tavily credits", rep.tavily_credits)
        m4.metric("Latency", f"{rep.latency_s:.1f}s")
        if rep.corrected_answer:
            st.success(f"**Corrected answer:** {rep.corrected_answer}")
        st.markdown("#### Claims")
        for c in rep.claims:
            with st.container(border=True):
                st.markdown(f"{badge(c.verdict)} &nbsp; **{c.claim}**", unsafe_allow_html=True)
                if c.time_sensitive:
                    st.caption(f"time-sensitive · volatility: {c.volatility} · Tavily query: “{c.search_query}”"
                               + (f" · confidence {c.confidence:.2f}" if c.confidence is not None else ""))
                    if c.explanation:
                        st.write(c.explanation)
                    if c.current_truth and c.verdict != "fresh":
                        st.info(f"**Current truth:** {c.current_truth}")
                    for u in c.evidence_urls:
                        st.markdown(f"- [{u}]({u})")
                else:
                    st.caption("evergreen: cannot go stale, not searched")
        with st.expander("Bifrost call trace (every LLM call went through the gateway)"):
            st.dataframe(pd.DataFrame(rep.llm_calls)[["purpose", "provider_used", "model_used", "prompt_tokens",
                                                       "completion_tokens", "latency_s", "fallback_used", "cost_usd"]],
                         use_container_width=True)

# ---------------- leaderboard ----------------
with tab_board:
    store = Store(S.db_path)
    runs = store.runs()
    if not runs:
        st.info("No benchmark runs yet: start one in the ▶️ tab or with `python -m freshbench run`.")
    else:
        labels = {f"{r['run_id']}  ·  {r['mode']}  ·  {r['n_tasks']} tasks  ·  judge {r['judge_model']}": r for r in runs}
        sel = labels[st.selectbox("Run", list(labels))]
        rows = store.results(sel["run_id"])
        df = pd.DataFrame(rows)
        lb = leaderboard(rows)
        if sel["mode"] == "simulation":
            st.warning("This run used SIMULATION mode (fictional world). Numbers demonstrate the pipeline, not real models.")
        best = lb.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏆 Top agent", f"{best['agent']}", best["model"])
        c2.metric("Best fresh rate", f"{lb['fresh_rate'].max():.0%}")
        cb = lb[lb["agent"] == "closed_book"]
        c3.metric("Closed-book stale rate", f"{cb['stale_rate'].mean():.0%}" if len(cb) else "n/a")
        c4.metric("Agent runs", len(df))
        show = lb.copy()
        for col in ("fresh_rate", "stale_rate", "unverified_rate", "error_rate"):
            show[col] = (show[col] * 100).round(0).astype(int).astype(str) + "%"
        st.dataframe(show[["agent", "model", "fresh_score", "fresh_rate", "stale_rate", "unverified_rate", "avg_cost_usd",
                           "cost_per_fresh_answer", "avg_latency_s", "avg_tokens", "fallbacks", "error_rate"]],
                     use_container_width=True, hide_index=True)
        g1, g2 = st.columns(2)
        fig = px.scatter(lb, x="avg_cost_usd", y="fresh_rate", color="agent", symbol="model", size_max=14,
                         title="Freshness vs cost per answer (top-left is best)", labels={"avg_cost_usd": "avg cost per answer (USD)", "fresh_rate": "fresh rate"})
        fig.update_traces(marker=dict(size=14))
        fig.update_yaxes(tickformat=".0%")
        g1.plotly_chart(fig, use_container_width=True)
        ok = df[df["verdict"].isin(["fresh", "stale", "incorrect", "unverifiable", "partially_verified"])]
        if len(ok):
            cat = ok.assign(stale=ok["verdict"].isin(["stale", "incorrect"])).groupby(["category", "agent"])["stale"].mean().reset_index()
            fig2 = px.bar(cat, x="category", y="stale", color="agent", barmode="group", title="Stale-answer rate by topic")
            fig2.update_yaxes(tickformat=".0%")
            g2.plotly_chart(fig2, use_container_width=True)
        st.markdown("#### Drill down")
        f1, f2 = st.columns(2)
        task = f1.selectbox("Question", sorted(df["question"].unique()))
        sub = df[df["question"] == task]
        for _, r in sub.iterrows():
            with st.container(border=True):
                st.markdown(f"{badge(r['verdict'])} &nbsp; **{r['agent']}** · `{r['model']}` · ${r['cost_usd']:.5f} · "
                            f"{r['latency_s'] or 0:.2f}s · via `{r['providers_used']}`", unsafe_allow_html=True)
                st.write(r["answer"] or r["error"])
                det = json.loads(r["detail"] or "{}")
                for c in det.get("judge", {}).get("claims", []):
                    if c["verdict"] in ("stale", "incorrect") and c.get("current_truth"):
                        st.caption(f"🕰️ “{c['claim']}” → now: {c['current_truth']}")

# ---------------- run ----------------
with tab_run:
    st.subheader("Run a benchmark")
    models_all = available_models()
    agents = st.multiselect("Agents", list(AGENTS), default=list(AGENTS),
                            help="; ".join(f"{k}: {v.description}" for k, v in AGENTS.items()))
    models = st.multiselect("Models (routed through Bifrost)", models_all, default=models_all[:2])
    fallbacks = st.multiselect("Bifrost fallback chain", models_all, default=[],
                               help="If a provider errors, Bifrost retries the call on these models automatically.")
    limit = st.slider("Number of tasks", 1, 30 if not S.simulate else 8, 5 if not S.simulate else 8)
    workers = st.slider("Parallel workers", 1, 8, 2)
    n_jobs = len(agents) * len(models) * limit
    st.caption(f"{n_jobs} agent runs. Each run is also judged by the Stale-Answer Detector.")
    if st.button("Start", type="primary", disabled=not (agents and models)):
        bar = st.progress(0.0)
        log = st.empty()

        def prog(done, total, row):
            bar.progress(done / total, text=f"{done}/{total}")
            log.write(f"{row['agent']} · {row['model']} · {row['task_id']} → **{row['verdict']}**")

        rid = run_benchmark(agents, models, limit=limit, workers=workers, s=S, fallbacks=fallbacks, progress=prog)
        st.success(f"Run {rid} finished: open the 🏆 Leaderboard tab.")

# ---------------- how ----------------
with tab_how:
    st.markdown("""
### Why FreshBench?
LLM agents confidently repeat facts that **used to be true**: last year's champion, a former CEO, an old library
version, last quarter's interest rate. Existing benchmarks freeze gold answers, so they go stale too.
FreshBench has **no frozen answers**: each answer is checked against the live web at evaluation time.

### Pipeline
```
 Agents under test ──► Bifrost gateway ──► OpenAI · Anthropic · Gemini · Groq …
   closed_book            │  virtual-key governance, fallbacks,
   search_rag ──► Tavily  │  per-call provider / tokens / latency
   guarded ──► Detector   │
          │               ▼
          └──► Stale-Answer Detector (fixed judge, also via Bifrost)
                 1. extract atomic claims, flag time-sensitive ones
                 2. Tavily search with a NEUTRAL query per claim (dated evidence)
                 3. verdict: fresh / stale / incorrect / unverifiable (+ citations)
                 4. optional auto-repair with an "as of" date
          ▼
   SQLite ──► leaderboard: fresh rate, stale rate, cost per fresh answer, latency, tokens, fallbacks, errors
```
### Metrics
* **Fresh rate**: share of time-sensitive answers verified current today.
* **Stale rate**: share containing outdated or contradicted claims.
* **Cost per fresh answer**: LLM cost (via Bifrost) + Tavily credits, divided by fresh answers.
* **FreshScore** = 100 × fresh rate × (1 − error rate) − 50 × stale rate.
""")
