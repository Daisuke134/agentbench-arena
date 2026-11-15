"""Model backends the harness proxies model calls to.

* ``mock``   : a deterministic local stand-in for an LLM (no key, no network).
* ``openai`` : any OpenAI-compatible /chat/completions endpoint, e.g. a Bifrost
               gateway (https://github.com/maximhq/bifrost) at http://localhost:8080/v1.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request

from . import mock_planner


class ModelUnavailable(Exception):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class MockBackend:
    name = "mock-planner-v0"
    price_in = 0.0   # USD per 1M tokens (local, free)
    price_out = 0.0

    def complete(self, messages, model=None):
        content = json.dumps(mock_planner.next_action(messages))
        prompt = sum(estimate_tokens(m.get("content") or "") for m in messages)
        return content, {"prompt_tokens": prompt, "completion_tokens": estimate_tokens(content),
                         "estimated": True, "model": self.name}


class OpenAICompatBackend:
    """Routes calls to AGENTBENCH_OPENAI_BASE_URL (point it at Bifrost to get
    provider fallback, budgets and observability for free)."""

    def __init__(self, base_url=None, api_key=None, model=None, timeout=60):
        self.base_url = (base_url or os.environ.get("AGENTBENCH_OPENAI_BASE_URL", "http://localhost:8080/v1")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("AGENTBENCH_OPENAI_API_KEY", "")
        self.name = model or os.environ.get("AGENTBENCH_MODEL", "openai/gpt-4o-mini")
        self.price_in = float(os.environ.get("AGENTBENCH_PRICE_IN_PER_M", "0"))
        self.price_out = float(os.environ.get("AGENTBENCH_PRICE_OUT_PER_M", "0"))
        self.timeout = timeout

    def complete(self, messages, model=None):
        body = json.dumps({"model": model or self.name, "messages": messages, "temperature": 0}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except Exception as e:  # network error, 5xx, etc.
            raise ModelUnavailable(f"model endpoint error: {type(e).__name__}") from None
        content = data["choices"][0]["message"].get("content") or ""
        u = data.get("usage") or {}
        if u:
            usage = {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0), "estimated": False}
        else:
            usage = {"prompt_tokens": sum(estimate_tokens(m.get("content") or "") for m in messages),
                     "completion_tokens": estimate_tokens(content), "estimated": True}
        usage["model"] = model or self.name
        return content, usage


def make_backend(kind: str | None = None):
    kind = kind or os.environ.get("AGENTBENCH_MODEL_BACKEND", "mock")
    if kind == "mock":
        return MockBackend()
    if kind == "openai":
        return OpenAICompatBackend()
    raise ValueError(f"unknown backend {kind}")
