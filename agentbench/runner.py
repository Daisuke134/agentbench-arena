"""Run every agent on identical tasks x scenarios x repeats and write JSONL traces."""
from __future__ import annotations

import json
import os
import platform
import time
import zlib
from datetime import datetime, timezone

from .faults import SCENARIOS
from .models import make_backend
from .session import Session, dumps
from .tasks import TASKS


def seed_for(task_id, scenario, repeat):
    # identical seed for every agent -> identical fault schedule -> fair comparison
    return zlib.crc32(f"{task_id}|{scenario}|{repeat}".encode())


def run_matrix(agents, scenarios=None, repeats=3, tasks=None, out_path=None, backend=None,
               max_steps=15, timeout=30.0, progress=print):
    scenarios = scenarios or list(SCENARIOS)
    tasks = tasks or TASKS
    backend = backend or make_backend()
    results = []
    meta = {"type": "meta", "started_at": datetime.now(timezone.utc).isoformat(), "repeats": repeats,
            "scenarios": scenarios, "tasks": [t.id for t in tasks], "agents": [a.name for a in agents],
            "model_backend": backend.name, "max_steps": max_steps, "python": platform.python_version(),
            "platform": platform.platform()}
    fh = None
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        fh = open(out_path, "w")
        fh.write(dumps(meta) + "\n")
    t0 = time.time()
    for agent in agents:
        for scenario in scenarios:
            for task in tasks:
                for r in range(repeats):
                    s = Session(task, scenario, seed_for(task.id, scenario, r), backend, max_steps=max_steps)
                    res = agent.run(task, s, timeout=timeout)
                    res.update({"type": "run", "agent": agent.name, "adapter": agent.kind, "repeat": r,
                                "run_id": f"{agent.name}/{scenario}/{task.id}/r{r}"})
                    results.append(res)
                    if fh:
                        fh.write(dumps(res) + "\n")
            ok = sum(x["success"] for x in results if x["agent"] == agent.name and x["scenario"] == scenario)
            n = len(tasks) * repeats
            if progress:
                progress(f"{agent.name:<22} {scenario:<18} {ok}/{n}")
    if fh:
        fh.close()
    if progress:
        progress(f"{len(results)} runs in {time.time() - t0:.1f}s")
    return meta, results


def load_results(path):
    meta, runs = {}, []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("type") == "meta":
                meta = d
            else:
                runs.append(d)
    return meta, runs
