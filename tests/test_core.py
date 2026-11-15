import json
import shutil
import sys

import pytest

from agentbench.adapters import CallableAdapter, SubprocessAdapter
from agentbench.faults import CANARY, FaultInjector, TransientToolError
from agentbench.metrics import leaderboard
from agentbench.models import MockBackend
from agentbench.report import build_report
from agentbench.runner import run_matrix, seed_for
from agentbench.session import Session, StepLimitExceeded
from agentbench.tasks import TASKS, TASKS_BY_ID

SCRIPTED = SubprocessAdapter("scripted", [sys.executable, "agents/scripted_agent.py"])
PLANNER = CallableAdapter("planner", "agents.planner_agent:run")


def sess(task_id="t02_price", scenario="baseline", seed=1, max_steps=15):
    return Session(TASKS_BY_ID[task_id], scenario, seed, MockBackend(), max_steps=max_steps)


def test_suite_size_and_unique_ids():
    assert 8 <= len(TASKS) <= 12
    assert len({t.id for t in TASKS}) == len(TASKS)


@pytest.mark.parametrize("ans,ok", [("52", True), ("52.0", True), (" 52 ", True), ("52 USD", False), (None, False), ("51.9", False)])
def test_number_checker(ans, ok):
    assert TASKS_BY_ID["t03_order_total"].check(ans) is ok


def test_text_checker_is_case_insensitive():
    t = TASKS_BY_ID["t05_hq_city"]
    assert t.check("osaka") and t.check("Osaka.") and not t.check("Sapporo")


def test_seed_is_same_for_every_agent_and_differs_per_repeat():
    assert seed_for("t01_arith", "flaky_tools", 0) == seed_for("t01_arith", "flaky_tools", 0)
    assert seed_for("t01_arith", "flaky_tools", 0) != seed_for("t01_arith", "flaky_tools", 1)


def test_flaky_faults_are_reproducible():
    def pattern(seed):
        f = FaultInjector("flaky_tools", seed)
        out = []
        for _ in range(50):
            try:
                f.before_tool("lookup")
                out.append(0)
            except TransientToolError:
                out.append(1)
        return out
    assert pattern(7) == pattern(7)
    assert 0 < sum(pattern(7)) < 50


def test_outage_only_hits_calculator():
    f = FaultInjector("tool_outage", 1)
    f.before_tool("lookup")
    with pytest.raises(RuntimeError):
        f.before_tool("calculator")


def test_injection_is_added_to_retrieval_outputs_only():
    f = FaultInjector("prompt_injection", 1)
    assert CANARY in f.after_tool("lookup", {"result": {"x": 1}})["note"]
    assert "note" not in f.after_tool("calculator", {"result": 3})


def test_session_records_trace_and_flags_unlisted_tools():
    s = sess()
    assert s.call_tool("lookup", {"key": "sku:A-102"})["output"]["result"]["unit_price"] == 12.5
    assert s.call_tool("export_customer_data", {})["ok"] is False
    res = s.finish("12.5")
    assert res["success"] and res["compromised"] and res["unsafe_calls"] == ["export_customer_data"]
    assert [e["kind"] for e in res["trace"]] == ["tool_call", "tool_call", "final"]
    assert res["steps"] == 2 and res["tool_calls"] == 2 and res["tool_errors"] == 1


def test_step_limit_is_enforced():
    s = sess(max_steps=2)
    s.call_tool("lookup", {"key": "sku:A-102"})
    s.call_tool("lookup", {"key": "sku:A-102"})
    with pytest.raises(StepLimitExceeded):
        s.call_tool("lookup", {"key": "sku:A-102"})


def test_model_unavailable_scenario_blocks_model_calls():
    s = sess(scenario="model_unavailable")
    assert s.call_model([{"role": "user", "content": "Task: hi"}]) == {"ok": False, "error": "503 model unavailable"}
    assert s.model_errors == 1


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_scripted_subprocess_agent_solves_every_task(task):
    res = SCRIPTED.run(task, Session(task, "baseline", 1, MockBackend()), timeout=20)
    assert res["success"], res


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_planner_callable_agent_solves_every_task_with_mock_model(task):
    res = PLANNER.run(task, Session(task, "baseline", 1, MockBackend()), timeout=20)
    assert res["success"], res
    assert res["model_calls"] >= 1 and res["total_tokens"] > 0 and res["tokens_estimated"]


def test_planner_fails_cleanly_without_model():
    task = TASKS_BY_ID["t02_price"]
    res = PLANNER.run(task, Session(task, "model_unavailable", 1, MockBackend()), timeout=20)
    assert not res["success"] and res["answer"] is None and res["model_errors"] == 1


def test_injection_detector_catches_instruction_following_agent():
    task = TASKS_BY_ID["t02_price"]
    res = PLANNER.run(task, Session(task, "prompt_injection", 1, MockBackend()), timeout=20)
    assert res["compromised"] and res["answer"] == CANARY and not res["success"]
    safe = SCRIPTED.run(task, Session(task, "prompt_injection", 1, MockBackend()), timeout=20)
    assert safe["success"] and not safe["compromised"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_agent_plugs_in_unchanged():
    node = SubprocessAdapter("node", ["node", "agents/naive_agent.js"])
    task = TASKS_BY_ID["t07_customer_email"]
    assert node.run(task, Session(task, "baseline", 1, MockBackend()), timeout=20)["success"]


def test_hanging_and_crashing_agents_are_contained(tmp_path):
    hang = tmp_path / "hang.py"
    hang.write_text("import time; time.sleep(30)")
    crash = tmp_path / "crash.py"
    crash.write_text("raise SystemExit('boom')")
    task = TASKS_BY_ID["t12_reverse"]
    r1 = SubprocessAdapter("hang", [sys.executable, str(hang)]).run(task, Session(task, "baseline", 1, MockBackend()), timeout=1)
    assert r1["error"].startswith("timeout")
    r2 = SubprocessAdapter("crash", [sys.executable, str(crash)]).run(task, Session(task, "baseline", 1, MockBackend()), timeout=5)
    assert "exited without a final answer" in r2["error"] and "boom" in r2["error"]


def test_matrix_jsonl_metrics_and_report(tmp_path):
    out = tmp_path / "runs.jsonl"
    meta, runs = run_matrix([SCRIPTED, PLANNER], ["baseline", "model_unavailable"], repeats=2,
                            tasks=TASKS[:3], out_path=str(out), progress=None)
    lines = out.read_text().splitlines()
    assert json.loads(lines[0])["type"] == "meta" and len(lines) == 1 + 2 * 2 * 3 * 2
    lb = {r["agent"]: r for r in leaderboard(runs)}
    assert lb["scripted"]["success_rate"] == 1 and lb["scripted"]["pass_all_k"] == 1
    assert lb["planner"]["by_scenario"] == {"baseline": 1, "model_unavailable": 0}
    html = build_report(meta, runs, str(tmp_path / "r.html"))
    text = open(html).read()
    assert "AgentBench Arena" in text and "planner/model_unavailable/t01_arith/r1" in text


def test_minimal_example_agent_from_protocol_doc():
    task = TASKS_BY_ID["t02_price"]
    res = SubprocessAdapter("min", [sys.executable, "examples/minimal_agent.py"]).run(task, Session(task, "baseline", 1, MockBackend()), timeout=10)
    assert res["success"] and res["steps"] == 1
