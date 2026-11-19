"""Settings, model catalog and pricing for FreshBench."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:  # optional: load .env when present
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
CACHE_DIR = ROOT / ".cache"

# Models FreshBench knows how to route through Bifrost.
# provider -> (env var holding the provider key, {model: (USD per 1M input tokens, USD per 1M output tokens)})
# Prices are approximate public list prices, used only when Bifrost does not report a cost itself.
# Add or edit models here; `python -m freshbench bifrost-config` regenerates bifrost/config.json.
MODEL_CATALOG: dict[str, tuple[str, dict[str, tuple[float, float]]]] = {
    "groq": ("GROQ_API_KEY", {
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant": (0.05, 0.08),
    }),
    "gemini": ("GEMINI_API_KEY", {
        "gemini-2.5-flash": (0.30, 2.50),
    }),
    "openai": ("OPENAI_API_KEY", {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4.1-mini": (0.40, 1.60),
    }),
    "anthropic": ("ANTHROPIC_API_KEY", {
        "claude-haiku-4-5": (1.00, 5.00),
    }),
    # Fictional models used by simulation mode (FRESHBENCH_SIMULATE=1).
    "sim": ("", {
        "oldie-8b": (0.05, 0.10),
        "newer-70b": (0.60, 0.80),
    }),
}

# Tavily pay-as-you-go price per API credit (basic search = 1 credit, advanced = 2).
TAVILY_USD_PER_CREDIT = 0.008


def model_price(model: str) -> tuple[float, float]:
    provider, _, name = model.partition("/")
    entry = MODEL_CATALOG.get(provider)
    if not entry:
        return (0.0, 0.0)
    return entry[1].get(name, (0.0, 0.0))


def available_models() -> list[str]:
    """Models whose provider key is present in the environment (or sim models in simulation mode)."""
    if settings().simulate:
        return [f"sim/{m}" for m in MODEL_CATALOG["sim"][1]]
    out = []
    for provider, (env, models) in MODEL_CATALOG.items():
        if provider != "sim" and env and os.getenv(env):
            out.extend(f"{provider}/{m}" for m in models)
    return out


@dataclass
class Settings:
    bifrost_url: str = field(default_factory=lambda: os.getenv("BIFROST_URL", "http://localhost:8080"))
    bifrost_virtual_key: str = field(default_factory=lambda: os.getenv("BIFROST_VIRTUAL_KEY", "sk-bf-freshbench"))
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    judge_model: str = field(default_factory=lambda: os.getenv("FRESHBENCH_JUDGE_MODEL", "groq/llama-3.3-70b-versatile"))
    simulate: bool = field(default_factory=lambda: os.getenv("FRESHBENCH_SIMULATE", "0") == "1")
    db_path: Path = field(default_factory=lambda: Path(os.getenv("FRESHBENCH_DB", str(RESULTS_DIR / "freshbench.db"))))
    today: str = field(default_factory=lambda: os.getenv("FRESHBENCH_TODAY", date.today().isoformat()))

    def __post_init__(self) -> None:
        if self.simulate and self.judge_model.split("/")[0] != "sim":
            self.judge_model = "sim/newer-70b"


def settings() -> Settings:
    return Settings()
