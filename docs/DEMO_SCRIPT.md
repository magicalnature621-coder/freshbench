# FreshBench: 3-minute demo video script

Record with OBS / Loom at 1080p. Before recording: `.env` filled, `docker compose up -d`, `streamlit run app.py`,
and one benchmark run done (`python -m freshbench run --limit 10`) so the leaderboard is populated.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Title slide | "AI agents confidently give answers that *used* to be true: last year's champion, an ex-CEO, an old version. FreshBench measures how often agents are out of date, and what it costs to fix it." |
| 0:20–0:45 | Architecture slide | "Every LLM call, from the agents under test and from the judge, goes through **Bifrost**. That gives us one API for every provider, virtual-key governance, fallbacks, and latency and token telemetry. Every fact is checked live with **Tavily**." |
| 0:45–1:30 | App → Detector tab, preset "FIFA World Cup" → Check freshness | "Here's a classic stale answer. The detector splits it into claims, marks them time-sensitive, searches Tavily with a *neutral* query, and judges each claim against dated evidence. Verdict: STALE. Here's the current truth, the sources, and an auto-repaired answer stamped 'as of today'." Expand **Bifrost call trace**: "Each step is a Bifrost call: provider, tokens, latency, cost." |
| 1:30–2:20 | Leaderboard tab | "Same models, different agent designs. Closed-book is cheap but stale X% of the time. search_rag and guarded are fresh, and the real question is **cost per fresh answer**, which is where Bifrost's cost and latency data matters." Point at the scatter plot and the stale-by-topic chart, then drill into one question. |
| 2:20–2:40 | Terminal: `python -m freshbench run ... --fallbacks gemini/gemini-2.5-flash` | "It's also a CLI. With a fallback chain, Bifrost fails over automatically and FreshBench counts every fallback per agent." |
| 2:40–3:00 | Browser `localhost:8080` (Bifrost UI logs), then the closing slide | "Every request is visible in Bifrost's logs. FreshBench has no frozen gold answers, so it never goes stale itself. Next step: ship the detector as a Bifrost plugin. Thanks!" |
