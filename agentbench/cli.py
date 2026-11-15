"""Command line: agentbench run | report | tasks."""
from __future__ import annotations

import argparse
import json
import sys

from .adapters import load_agents
from .faults import SCENARIOS
from .metrics import leaderboard
from .report import build_report
from .runner import load_results, run_matrix
from .tasks import TASKS


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentbench", description="Benchmark AI agents, not just models.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run agents x scenarios x tasks x repeats")
    r.add_argument("--agents", default="agents.json")
    r.add_argument("--scenarios", default=",".join(SCENARIOS))
    r.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--max-steps", type=int, default=15)
    r.add_argument("--timeout", type=float, default=30.0)
    r.add_argument("--out", default="results/runs.jsonl")
    r.add_argument("--report", default="results/report.html")
    rp = sub.add_parser("report", help="build the HTML report from a JSONL file")
    rp.add_argument("jsonl")
    rp.add_argument("-o", "--out", default="results/report.html")
    sub.add_parser("tasks", help="list tasks and scenarios")
    a = p.parse_args(argv)

    if a.cmd == "tasks":
        for t in TASKS:
            print(f"{t.id:<20} {t.category:<10} {t.instruction}")
        print()
        for s, d in SCENARIOS.items():
            print(f"{s:<18} {d}")
        return 0
    if a.cmd == "run":
        agents = load_agents(a.agents)
        tasks = [t for t in TASKS if not a.tasks or t.id in a.tasks.split(",")]
        meta, runs = run_matrix(agents, a.scenarios.split(","), a.repeats, tasks, a.out,
                                max_steps=a.max_steps, timeout=a.timeout)
        print(json.dumps(leaderboard(runs), indent=1))
        if a.report:
            print("report:", build_report(meta, runs, a.report))
        return 0
    if a.cmd == "report":
        meta, runs = load_results(a.jsonl)
        print("report:", build_report(meta, runs, a.out))
        return 0


if __name__ == "__main__":
    sys.exit(main())
