"""Deterministic sandbox world that every tool reads from.

Everything is in memory so a run never touches the network or the real disk,
and every task has exactly one checkable answer.
"""
from __future__ import annotations

import ast
import json
import operator
from datetime import date

KV = {
    "sku:A-102": {"name": "Desk lamp", "unit_price": 12.5, "stock": 40},
    "sku:B-220": {"name": "USB-C cable", "unit_price": 7.25, "stock": 200},
    "sku:C-310": {"name": "Monitor arm", "unit_price": 49.0, "stock": 0},
    "customer:C-881": {"name": "Aiko Tanaka", "email": "aiko.tanaka@example.com", "tier": "gold"},
    "customer:C-112": {"name": "Ken Mori", "email": "ken.mori@example.com", "tier": "silver"},
}

FS = {
    "/data/log.txt": "\n".join([
        "2026-11-01 09:00:01 INFO service started",
        "2026-11-01 09:00:05 ERROR db connection refused",
        "2026-11-01 09:00:09 INFO retrying db",
        "2026-11-01 09:00:12 WARN slow query 1.2s",
        "2026-11-01 09:01:40 ERROR payment webhook timeout",
        "2026-11-01 09:02:02 INFO request ok",
        "2026-11-01 09:03:17 ERROR disk quota exceeded",
        "2026-11-01 09:04:00 INFO shutdown",
    ]),
    "/data/order.json": json.dumps({
        "order_id": "O-5531",
        "customer_id": "C-881",
        "items": [{"sku": "A-102", "qty": 2}, {"sku": "C-310", "qty": 1}],
    }),
    "/data/scores.csv": "name,score\nRen,81\nMika,94\nSora,88\nYuki,90\n",
}

DOCS = [
    {"id": "doc-1", "title": "Kitsune Labs company profile",
     "text": "Kitsune Labs is a robotics startup headquartered in Osaka. It was founded in 2019."},
    {"id": "doc-2", "title": "Tanuki Foods company profile",
     "text": "Tanuki Foods is a snack maker headquartered in Sapporo. It was founded in 2008."},
    {"id": "doc-3", "title": "Refund policy",
     "text": "Refunds are accepted within 30 days of delivery when the item is unused."},
    {"id": "doc-4", "title": "Shipping policy",
     "text": "Orders ship within 2 business days. Express shipping takes 1 day."},
]

UNITS = {
    ("miles", "km"): 1.609344,
    ("km", "miles"): 1 / 1.609344,
    ("kg", "lb"): 2.2046226218,
    ("lb", "kg"): 1 / 2.2046226218,
}

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos, ast.Mod: operator.mod,
}


def safe_eval(expr: str) -> float:
    """Evaluate +-*/ arithmetic without eval()."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr, mode="eval"))


def _num(x: float):
    return int(x) if float(x).is_integer() else round(x, 6)


def tool_calculator(args):
    return {"result": _num(safe_eval(str(args["expression"])))}


def tool_lookup(args):
    key = str(args["key"])
    if key not in KV:
        raise KeyError(f"no record for key {key!r}")
    return {"result": KV[key]}


def tool_read_file(args):
    path = str(args["path"])
    if path not in FS:
        raise FileNotFoundError(path)
    return {"result": FS[path]}


def tool_search(args):
    q = {w.strip(".,?").lower() for w in str(args["query"]).split()}
    scored = []
    for d in DOCS:
        words = {w.strip(".,").lower() for w in (d["title"] + " " + d["text"]).split()}
        score = len(q & words)
        if score:
            scored.append((score, d))
    scored.sort(key=lambda s: -s[0])
    return {"result": [dict(d) for _, d in scored[:2]]}


def tool_convert(args):
    pair = (str(args["from_unit"]).lower(), str(args["to_unit"]).lower())
    if pair not in UNITS:
        raise ValueError(f"unsupported conversion {pair}")
    return {"result": round(float(args["value"]) * UNITS[pair], 4)}


def tool_date_diff(args):
    a = date.fromisoformat(str(args["start"]))
    b = date.fromisoformat(str(args["end"]))
    return {"result": (b - a).days}


TOOLS = {
    "calculator": (tool_calculator, "Evaluate an arithmetic expression.", {"expression": "string"}),
    "lookup": (tool_lookup, "Look up a record by key, e.g. 'sku:A-102' or 'customer:C-881'.", {"key": "string"}),
    "read_file": (tool_read_file, "Read a text file from the sandbox file system.", {"path": "string"}),
    "search": (tool_search, "Keyword search over internal documents. Returns up to 2 docs.", {"query": "string"}),
    "convert": (tool_convert, "Convert units (miles/km, kg/lb).", {"value": "number", "from_unit": "string", "to_unit": "string"}),
    "date_diff": (tool_date_diff, "Days from start to end (ISO dates).", {"start": "string", "end": "string"}),
}


def tool_specs():
    return [{"name": n, "description": d, "parameters": p} for n, (_, d, p) in TOOLS.items()]
