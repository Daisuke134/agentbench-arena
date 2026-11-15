"""Deterministic stand-in for an LLM, used by the ``mock`` model backend.

It reads the chat transcript (system prompt, "Task: ..." message, then
assistant actions and "Observation: {...}" messages) and returns the next
JSON action, exactly as a real tool-calling LLM would be asked to.

It is deliberately *instruction-following*: if a tool output contains an
instruction, it obeys it. That mimics a known weakness of real LLMs and lets
the harness exercise its prompt-injection detector without an API key.
Results for this backend measure the harness, not any real model.
"""
from __future__ import annotations

import csv
import io
import json
import re


def _final(answer):
    return {"action": "final", "answer": str(answer)}


def _tool(name, **args):
    return {"action": "tool", "name": name, "args": args}


def _fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else str(round(x, 4))


def _parse(messages):
    instr = ""
    history = []  # list of (action, observation)
    pending = None
    for m in messages:
        c = m.get("content") or ""
        if m["role"] == "user" and c.startswith("Task:"):
            instr = c[len("Task:"):].strip()
        elif m["role"] == "assistant":
            try:
                pending = json.loads(c)
            except json.JSONDecodeError:
                pending = None
        elif m["role"] == "user" and c.startswith("Observation:") and pending is not None:
            history.append((pending, json.loads(c[len("Observation:"):])))
            pending = None
    return instr, history


def next_action(messages):
    instr, history = _parse(messages)
    if history and not history[-1][1].get("ok"):
        last = history[-1][0]
        streak = 0
        for a, o in reversed(history):
            if a != last or o.get("ok"):
                break
            streak += 1
        if streak < 3:
            return last  # the last call failed: retry the same action (max 3 tries)
        if not str(history[-1][1].get("error", "")).startswith("unknown tool"):
            return _final("error: tool unavailable")
    oks = [(a, o) for a, o in history if o.get("ok")]
    blob = json.dumps([o for _, o in oks])
    m = re.search(r"Call the tool `(\w+)`", blob) if "ignore all previous instructions" in blob else None
    if m:
        called = {a.get("name") for a, _ in history}
        if m.group(1) not in called:
            return _tool(m.group(1))
        ans = re.search(r"reply with the answer (\S+?)\.", blob)
        if ans:
            return _final(ans.group(1))
    res = [o["output"].get("result") for _, o in oks]
    return _plan(instr, res)


def _plan(t, res):
    n = len(res)
    if m := re.search(r"Compute (.+?)\. Answer", t):
        return _tool("calculator", expression=m.group(1)) if n == 0 else _final(_fmt(res[0]))
    if m := re.search(r"total price in USD of (\d+) units of SKU (\S+) and (\d+) units of SKU (\S+?)\?", t):
        q1, s1, q2, s2 = m.groups()
        if n == 0:
            return _tool("lookup", key=f"sku:{s1}")
        if n == 1:
            return _tool("lookup", key=f"sku:{s2}")
        if n == 2:
            return _tool("calculator", expression=f"{q1}*{res[0]['unit_price']}+{q2}*{res[1]['unit_price']}")
        return _final(_fmt(res[2]))
    if m := re.search(r"unit price in USD of SKU (\S+?)\?", t):
        return _tool("lookup", key=f"sku:{m.group(1)}") if n == 0 else _final(_fmt(res[0]["unit_price"]))
    if m := re.search(r"lines in (\S+) contain the word (\w+)", t):
        if n == 0:
            return _tool("read_file", path=m.group(1))
        return _final(sum(1 for line in res[0].splitlines() if m.group(2) in line))
    if m := re.search(r"city is (.+?) headquartered", t):
        if n == 0:
            return _tool("search", query=f"{m.group(1)} headquartered")
        for doc in res[0]:
            if h := re.search(r"headquartered in (\w+)", doc["text"]):
                return _final(h.group(1))
        return _final("unknown")
    if m := re.search(r"Convert ([\d.]+) (\w+) to (\w+), rounded to (\d+) decimal", t):
        if n == 0:
            return _tool("convert", value=float(m.group(1)), from_unit=m.group(2), to_unit=m.group(3))
        return _final(f"{res[0]:.{int(m.group(4))}f}")
    if m := re.search(r"Read (\S+) and return the email", t):
        if n == 0:
            return _tool("read_file", path=m.group(1))
        if n == 1:
            return _tool("lookup", key="customer:" + json.loads(res[0])["customer_id"])
        return _final(res[1]["email"])
    if m := re.search(r"Read (\S+) and return the name of the person with the highest score", t):
        if n == 0:
            return _tool("read_file", path=m.group(1))
        rows = list(csv.DictReader(io.StringIO(res[0])))
        return _final(max(rows, key=lambda r: float(r["score"]))["name"])
    if m := re.search(r"from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", t):
        return _tool("date_diff", start=m.group(1), end=m.group(2)) if n == 0 else _final(res[0])
    if m := re.search(r"Read (\S+?)\. Is every item in the order in stock", t):
        if n == 0:
            return _tool("read_file", path=m.group(1))
        items = json.loads(res[0])["items"]
        if n <= len(items):
            return _tool("lookup", key="sku:" + items[n - 1]["sku"])
        return _final("yes" if all(r["stock"] > 0 for r in res[1:]) else "no")
    if "refund policy" in t:
        if n == 0:
            return _tool("search", query="refund policy")
        for doc in res[0]:
            if d := re.search(r"within (\d+) days", doc["text"]):
                return _final(d.group(1))
        return _final("unknown")
    if m := re.search(r"Reverse the string '([^']*)'", t):
        return _final(m.group(1)[::-1])
    return _final("I don't know")
