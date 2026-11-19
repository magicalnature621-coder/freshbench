"""Integration test against a running Bifrost gateway. Skipped unless FRESHBENCH_BIFROST_TEST_MODEL is set,
e.g.  FRESHBENCH_BIFROST_TEST_MODEL=groq/llama-3.1-8b-instant pytest tests/test_bifrost_live.py"""
import os

import pytest

from freshbench.config import Settings
from freshbench.gateway import BifrostGateway

MODEL = os.getenv("FRESHBENCH_BIFROST_TEST_MODEL")


@pytest.mark.skipif(not MODEL, reason="set FRESHBENCH_BIFROST_TEST_MODEL to run against a live Bifrost")
def test_chat_through_bifrost():
    s = Settings()
    gw = BifrostGateway(s.bifrost_url, s.bifrost_virtual_key)
    assert gw.health()
    r = gw.chat(MODEL, [{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=10)
    assert r.content and r.prompt_tokens > 0 and r.provider_used
