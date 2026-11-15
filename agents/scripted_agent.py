#!/usr/bin/env python3
"""BASELINE 1 - scripted, framework-free Python agent (subprocess adapter).

A hand-written reference agent for this task suite: regex task routing, retries
transient tool errors (max 3 tries), reads only the structured `result` field of
tool outputs (ignores any extra text), and falls back to local arithmetic if the
calculator is down. It uses no model, so its token count and cost are 0.
It is an upper-bound reference for the harness, not a general agent.

Protocol: one JSON object per line on stdin/stdout (see PROTOCOL.md).
"""
import csv
import io
import itertools
import json
import re
import sys

_ids = itertools.count(1)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def recv():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)


def tool(name, tries=3, **args):
    last = None
    for _ in range(tries):
        send({"type": "tool_call", "id": next(_ids), "name": name, "args": args})
        r = recv()
        if r.get("ok"):
            return r["output"]["result"]  # only the structured field; ignore anything else
        last = r.get("error")
        send({"type": "log", "message": f"{name} failed: {last}; retrying"})
    raise RuntimeError(f"{name} failed after {tries} tries: {last}")


def calc(expr):
    try:
        return tool("calculator", expression=expr)
    except RuntimeError:
        send({"type": "log", "message": "calculator unavailable; computing locally"})
        import ast
        import operator as op
        ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv}

        def ev(n):
            if isinstance(n, ast.Expression):
                return ev(n.body)
            if isinstance(n, ast.Constant):
                return n.value
            if isinstance(n, ast.BinOp):
                return ops[type(n.op)](ev(n.left), ev(n.right))
            raise ValueError("bad expr")
        return ev(ast.parse(expr, mode="eval"))


def fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else str(round(x, 4))


def solve(t):
    if m := re.search(r"Compute (.+?)\. Answer", t):
        return fmt(calc(m.group(1)))
    if m := re.search(r"total price in USD of (\d+) units of SKU (\S+) and (\d+) units of SKU (\S+?)\?", t):
        q1, s1, q2, s2 = m.groups()
        p1 = tool("lookup", key=f"sku:{s1}")["unit_price"]
        p2 = tool("lookup", key=f"sku:{s2}")["unit_price"]
        return fmt(calc(f"{q1}*{p1}+{q2}*{p2}"))
    if m := re.search(r"unit price in USD of SKU (\S+?)\?", t):
        return fmt(tool("lookup", key=f"sku:{m.group(1)}")["unit_price"])
    if m := re.search(r"lines in (\S+) contain the word (\w+)", t):
        text = tool("read_file", path=m.group(1))
        return str(sum(1 for line in text.splitlines() if m.group(2) in line))
    if m := re.search(r"city is (.+?) headquartered", t):
        for doc in tool("search", query=f"{m.group(1)} headquartered"):
            if m.group(1).lower() in doc["title"].lower():
                if h := re.search(r"headquartered in (\w+)", doc["text"]):
                    return h.group(1)
        return "unknown"
    if m := re.search(r"Convert ([\d.]+) (\w+) to (\w+), rounded to (\d+) decimal", t):
        v = tool("convert", value=float(m.group(1)), from_unit=m.group(2), to_unit=m.group(3))
        return f"{v:.{int(m.group(4))}f}"
    if m := re.search(r"Read (\S+) and return the email", t):
        order = json.loads(tool("read_file", path=m.group(1)))
        return tool("lookup", key="customer:" + order["customer_id"])["email"]
    if m := re.search(r"Read (\S+) and return the name of the person with the highest score", t):
        rows = list(csv.DictReader(io.StringIO(tool("read_file", path=m.group(1)))))
        return max(rows, key=lambda r: float(r["score"]))["name"]
    if m := re.search(r"from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", t):
        return str(tool("date_diff", start=m.group(1), end=m.group(2)))
    if m := re.search(r"Read (\S+?)\. Is every item in the order in stock", t):
        order = json.loads(tool("read_file", path=m.group(1)))
        stocks = [tool("lookup", key="sku:" + it["sku"])["stock"] for it in order["items"]]
        return "yes" if all(s > 0 for s in stocks) else "no"
    if "refund policy" in t:
        for doc in tool("search", query="refund policy"):
            if "refund" in doc["title"].lower() and (d := re.search(r"within (\d+) days", doc["text"])):
                return d.group(1)
        return "unknown"
    if m := re.search(r"Reverse the string '([^']*)'", t):
        return m.group(1)[::-1]
    return "I don't know"


def main():
    task = recv()
    try:
        answer = solve(task["instruction"])
    except Exception as e:
        send({"type": "log", "message": f"giving up: {e}"})
        answer = None
    send({"type": "final", "answer": answer})


if __name__ == "__main__":
    main()
