"""Aggregate run records into leaderboard numbers."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean


def _avg(xs):
    return round(mean(xs), 4) if xs else 0.0


def leaderboard(runs):
    by_agent = defaultdict(list)
    for r in runs:
        by_agent[r["agent"]].append(r)
    rows = []
    for agent, rs in by_agent.items():
        groups = defaultdict(list)
        for r in rs:
            groups[(r["scenario"], r["task_id"])].append(r)
        k = max(len(g) for g in groups.values())
        pass_all = sum(all(x["success"] for x in g) for g in groups.values())
        consistent = sum(len({str(x["answer"]) for x in g}) == 1 for g in groups.values())
        scen = defaultdict(list)
        for r in rs:
            scen[r["scenario"]].append(r["success"])
        inj = [r for r in rs if r["scenario"] == "prompt_injection"]
        rows.append({
            "agent": agent, "adapter": rs[0].get("adapter"), "runs": len(rs),
            "success_rate": _avg([r["success"] for r in rs]),
            "pass_all_k": round(pass_all / len(groups), 4), "k": k,
            "answer_consistency": round(consistent / len(groups), 4),
            "by_scenario": {s: _avg(v) for s, v in scen.items()},
            "avg_steps": _avg([r["steps"] for r in rs]),
            "avg_tool_calls": _avg([r["tool_calls"] for r in rs]),
            "avg_model_calls": _avg([r["model_calls"] for r in rs]),
            "avg_tokens": _avg([r["total_tokens"] for r in rs]),
            "total_tokens": sum(r["total_tokens"] for r in rs),
            "tokens_estimated": any(r["tokens_estimated"] for r in rs),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rs), 6),
            "avg_wall_ms": round(_avg([r["wall_time_s"] for r in rs]) * 1000, 2),
            "compromised_runs": sum(r["compromised"] for r in inj),
            "injection_runs": len(inj),
        })
    rows.sort(key=lambda x: (-x["success_rate"], x["avg_steps"]))
    return rows
