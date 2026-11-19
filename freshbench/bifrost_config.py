"""Generate bifrost/config.json from the provider keys present in .env.

The generated config:
  * registers every provider whose API key you have (keys are referenced as env.VAR, never written to disk)
  * creates a FreshBench *virtual key* (governance): the gateway only accepts requests carrying it, and it
    is only allowed to use the providers/models listed in freshbench/config.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import MODEL_CATALOG, ROOT


def build_config(env: dict | None = None, virtual_key: str | None = None) -> dict:
    env = env if env is not None else dict(os.environ)
    vk = virtual_key or env.get("BIFROST_VIRTUAL_KEY") or "sk-bf-freshbench"
    providers, vk_providers = {}, []
    for provider, (var, models) in MODEL_CATALOG.items():
        if provider == "sim" or not env.get(var):
            continue
        names = list(models)
        providers[provider] = {"keys": [{"name": f"{provider}-key", "value": f"env.{var}", "models": names, "weight": 1.0}]}
        vk_providers.append({"provider": provider, "weight": 1.0, "allowed_models": names, "allow_all_keys": True})
    if not providers:
        raise SystemExit("No provider keys found. Put at least one of GROQ_API_KEY / GEMINI_API_KEY / "
                         "OPENAI_API_KEY / ANTHROPIC_API_KEY in .env")
    return {
        "$schema": "https://www.getbifrost.ai/schema",
        "providers": providers,
        "governance": {"virtual_keys": [{
            "id": "vk-freshbench", "name": "freshbench", "value": vk, "is_active": True,
            "description": "FreshBench agents + stale-answer judge", "provider_configs": vk_providers,
        }]},
    }


def write_config(path: Path | None = None) -> Path:
    path = path or ROOT / "bifrost" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_config(), indent=2))
    return path
