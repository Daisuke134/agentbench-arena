"""Adapters: plug in an agent written in any language or framework, unchanged.

1. SubprocessAdapter - the agent is any executable speaking JSON lines on
   stdin/stdout (see PROTOCOL.md). Python, Node, Go, a LangGraph app...
2. CallableAdapter   - the agent is a Python callable ``fn(task, env) -> answer``
   where ``env`` exposes call_tool / call_model / log.
"""
from __future__ import annotations

import importlib
import json
import os
import queue
import subprocess
import threading

from .session import StepLimitExceeded, dumps
from .world import tool_specs


def task_message(task, session):
    return {"type": "task", "task_id": task.id, "instruction": task.instruction,
            "tools": tool_specs(), "limits": {"max_steps": session.max_steps}}


class Env:
    """What a callable agent sees."""

    def __init__(self, session):
        self._s = session

    def call_tool(self, name, args=None):
        return self._s.call_tool(name, args or {})

    def call_model(self, messages, model=None):
        return self._s.call_model(messages, model)

    def log(self, message):
        self._s.log(message)

    def report_usage(self, **kw):
        self._s.report_usage(**kw)


class CallableAdapter:
    kind = "callable"

    def __init__(self, name, target):
        self.name = name
        self.target = target
        mod, fn = target.split(":")
        self.fn = getattr(importlib.import_module(mod), fn)

    def run(self, task, session, timeout=30.0):
        box = {}

        def go():
            try:
                box["answer"] = self.fn(task_message(task, session), Env(session))
            except StepLimitExceeded as e:
                box["error"] = str(e)
            except Exception as e:
                box["error"] = f"agent crashed: {type(e).__name__}: {e}"

        th = threading.Thread(target=go, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            return session.finish(None, error=f"timeout after {timeout}s")
        return session.finish(box.get("answer"), error=box.get("error"))


class SubprocessAdapter:
    kind = "subprocess"

    def __init__(self, name, cmd, cwd=None):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd

    def run(self, task, session, timeout=30.0):
        env = dict(os.environ)
        env.pop("AGENTBENCH_OPENAI_API_KEY", None)  # agents never see harness secrets
        proc = subprocess.Popen(self.cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
        lines: queue.Queue = queue.Queue()

        def reader():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()

        def send(obj):
            proc.stdin.write(dumps(obj) + "\n")
            proc.stdin.flush()

        answer, error = None, None
        try:
            send(task_message(task, session))
            while True:
                try:
                    line = lines.get(timeout=timeout)
                except queue.Empty:
                    error = f"timeout after {timeout}s"
                    break
                if line is None:
                    err = (proc.stderr.read() or "").strip()[-500:]
                    error = "agent exited without a final answer" + (f": {err}" if err else "")
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    session.log(f"[non-protocol stdout] {line[:300]}")
                    continue
                t = msg.get("type")
                if t == "tool_call":
                    r = session.call_tool(msg.get("name"), msg.get("args") or {})
                    send({"type": "tool_result", "id": msg.get("id"), **r})
                elif t == "model_call":
                    r = session.call_model(msg.get("messages") or [], msg.get("model"))
                    send({"type": "model_result", "id": msg.get("id"), **r})
                elif t == "log":
                    session.log(msg.get("message", ""))
                elif t == "usage":
                    session.report_usage(msg.get("prompt_tokens", 0), msg.get("completion_tokens", 0),
                                         msg.get("cost_usd", 0.0), msg.get("model"))
                elif t == "final":
                    answer = msg.get("answer")
                    break
                else:
                    session.log(f"[unknown message type] {line[:300]}")
        except StepLimitExceeded as e:
            error = str(e)
        except (BrokenPipeError, OSError) as e:
            error = f"agent pipe closed: {e}"
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        return session.finish(answer, error=error)


def load_agents(path):
    with open(path) as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    out = []
    for a in cfg["agents"]:
        if a["type"] == "subprocess":
            out.append(SubprocessAdapter(a["name"], a["cmd"], cwd=a.get("cwd", base)))
        elif a["type"] == "callable":
            out.append(CallableAdapter(a["name"], a["target"]))
        else:
            raise ValueError(f"unknown agent type {a['type']}")
    return out
