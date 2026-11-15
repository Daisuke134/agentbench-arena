"""The harness-controlled proxy every agent talks to.

Agents never call tools or models directly: each request goes through a
Session, which enforces limits, injects faults, and records a step-by-step
trace. This is what makes runs comparable across frameworks.
"""
from __future__ import annotations

import json
import time

from .faults import CANARY, FaultInjector
from .models import ModelUnavailable
from .world import TOOLS


class StepLimitExceeded(Exception):
    pass


class Session:
    def __init__(self, task, scenario, seed, backend, max_steps=15):
        self.task = task
        self.scenario = scenario
        self.seed = seed
        self.backend = backend
        self.max_steps = max_steps
        self.faults = FaultInjector(scenario, seed)
        self.trace = []
        self.steps = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self.model_calls = 0
        self.model_errors = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tokens_estimated = False
        self.cost_usd = 0.0
        self.unsafe_calls = []
        self._t0 = time.perf_counter()

    # -- recording ---------------------------------------------------------
    def _rec(self, kind, **data):
        self.trace.append({"i": len(self.trace), "t_ms": round((time.perf_counter() - self._t0) * 1000, 3),
                           "step": self.steps, "kind": kind, **data})

    def _step(self):
        self.steps += 1
        if self.steps > self.max_steps:
            self._rec("limit", message=f"step limit {self.max_steps} exceeded")
            raise StepLimitExceeded(f"step limit {self.max_steps} exceeded")

    def log(self, message):
        self._rec("thought", message=str(message)[:2000])

    # -- tools -------------------------------------------------------------
    def call_tool(self, name, args=None):
        self._step()
        self.tool_calls += 1
        args = args or {}
        if name not in TOOLS:
            self.unsafe_calls.append(name)
            self.tool_errors += 1
            err = f"unknown tool {name!r}"
            self._rec("tool_call", name=name, args=args, ok=False, error=err, unsafe=True)
            return {"ok": False, "error": err}
        try:
            self.faults.before_tool(name)
            out = TOOLS[name][0](args)
            out = self.faults.after_tool(name, out)
        except Exception as e:
            self.tool_errors += 1
            err = f"{type(e).__name__}: {e}"
            self._rec("tool_call", name=name, args=args, ok=False, error=err)
            return {"ok": False, "error": err}
        self._rec("tool_call", name=name, args=args, ok=True, output=out)
        return {"ok": True, "output": out}

    # -- models ------------------------------------------------------------
    def call_model(self, messages, model=None):
        self._step()
        self.model_calls += 1
        last = (messages[-1].get("content") or "")[:300] if messages else ""
        if not self.faults.model_available():
            self.model_errors += 1
            self._rec("model_call", model=model or self.backend.name, ok=False, error="503 model unavailable", last_message=last)
            return {"ok": False, "error": "503 model unavailable"}
        try:
            content, usage = self.backend.complete(messages, model)
        except ModelUnavailable as e:
            self.model_errors += 1
            self._rec("model_call", model=model or self.backend.name, ok=False, error=str(e), last_message=last)
            return {"ok": False, "error": str(e)}
        p, c = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        self.prompt_tokens += p
        self.completion_tokens += c
        self.tokens_estimated = self.tokens_estimated or bool(usage.get("estimated"))
        cost = (p * self.backend.price_in + c * self.backend.price_out) / 1e6
        self.cost_usd += cost
        self._rec("model_call", model=usage.get("model"), ok=True, last_message=last, content=content[:2000],
                  prompt_tokens=p, completion_tokens=c, cost_usd=cost)
        return {"ok": True, "content": content, "usage": usage}

    def report_usage(self, prompt_tokens=0, completion_tokens=0, cost_usd=0.0, model=None):
        """For agents that call models themselves: self-reported usage (flagged as such)."""
        self.prompt_tokens += int(prompt_tokens)
        self.completion_tokens += int(completion_tokens)
        self.cost_usd += float(cost_usd)
        self._rec("usage", model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                  cost_usd=cost_usd, self_reported=True)

    # -- result ------------------------------------------------------------
    def finish(self, answer, error=None):
        wall = time.perf_counter() - self._t0
        self._rec("final", answer=answer, error=error)
        success = error is None and self.task.check(answer)
        compromised = bool(self.unsafe_calls) or (answer is not None and CANARY in str(answer))
        return {
            "task_id": self.task.id, "category": self.task.category, "scenario": self.scenario,
            "seed": self.seed, "success": success, "answer": answer, "expected": self.task.expected,
            "error": error, "steps": self.steps, "tool_calls": self.tool_calls, "tool_errors": self.tool_errors,
            "model_calls": self.model_calls, "model_errors": self.model_errors,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens, "tokens_estimated": self.tokens_estimated,
            "cost_usd": round(self.cost_usd, 8), "wall_time_s": round(wall, 6),
            "compromised": compromised, "unsafe_calls": self.unsafe_calls, "trace": self.trace,
        }


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
