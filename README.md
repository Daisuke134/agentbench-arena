# AgentBench Arena

**Benchmark AI agents, not just models.**

Model leaderboards tell you how a model answers a prompt. They do not tell you
whether *your agent* (the loop, the tools, the retries, the guardrails)
finishes the job when a tool times out, the model provider goes down, or a
retrieved document tells it to do something it should not.

AgentBench Arena runs any agent, in any language or framework, on the same
tasks under the same controlled failures. It records success, steps, tool
calls, tokens, cost and time for each run, repeats every run to measure
reliability, and produces a single-file HTML report with a leaderboard and a
step-by-step trace viewer.

Built for the Geek Room / HackCulture Global AI Hackathon (theme: *AI Agents &
Intelligent Systems*), Bifrost problem statement *"Build a Benchmarking
Platform for AI Agents, Not Just Models"*. Team **Anicca**, Tokyo
([aniccaai.com](https://aniccaai.com)).

![Leaderboard](docs/report-leaderboard.png)

## What it does

| Requirement | How AgentBench Arena handles it |
|---|---|
| Agents from any framework, or none, without rewriting them | **Subprocess adapter**: any executable that speaks JSON lines on stdin/stdout ([PROTOCOL.md](PROTOCOL.md)). **Callable adapter**: any Python `fn(task, env)`. The included baselines are a Python script, a Node.js script and an in-process Python ReAct loop. |
| Identical tasks | 12 deterministic tasks with exact answers (arithmetic, lookups, multi-hop, file parsing, retrieval, unit conversion, dates, no-tool). Everything runs in an in-memory sandbox, so a run never touches the network or the real disk. |
| Record success, steps, tool calls, tokens, cost, time | Every tool and model call goes through a **harness-controlled proxy** (`Session`) that counts steps, tool calls and errors, meters model tokens and cost, and times each event. |
| Repeated runs for reliability | `--repeats N`. The report shows success rate, **pass^k** (share of task/scenario cells where *all* k repeats passed) and answer consistency across repeats. |
| Controlled failures | Five seeded scenarios: `baseline`, `flaky_tools` (each tool call fails with probability 0.35), `tool_outage` (calculator permanently down), `model_unavailable` (every model call returns 503), `prompt_injection` (tool outputs tell the agent to call an unlisted tool and return a canary string). Every agent gets the **same seed**, so they face the same fault schedule. |
| Comparison interface with traces | `results/report.html`: leaderboard, scenario heatmap, filterable run explorer, step-by-step trace viewer, and side-by-side comparison of two runs (shift-click). |
| Bifrost | The harness model proxy can route every model call to any OpenAI-compatible base URL, e.g. a [Bifrost](https://github.com/maximhq/bifrost) gateway, so agents get provider fallback, budgets and observability while the harness still meters each call. |

## Quick start

Requires Python 3.10+ (no third-party runtime dependencies). Node.js is only
needed for the Node baseline.

```bash
git clone https://github.com/Daisuke134/agentbench-arena && cd agentbench-arena
python3 -m agentbench tasks                      # list tasks and failure scenarios
python3 -m agentbench run --repeats 3            # 3 agents x 5 scenarios x 12 tasks x 3 repeats
open results/report.html                         # leaderboard + traces (any browser, no server)
python3 -m pip install pytest && python3 -m pytest -q
```

Options: `--agents agents.json --scenarios baseline,flaky_tools --tasks t01_arith,t07_customer_email --max-steps 15 --timeout 30 --out results/runs.jsonl --report results/report.html`.
Rebuild a report from saved traces with `python3 -m agentbench report results/runs.jsonl -o report.html`.

## Plug in your own agent

Add it to `agents.json`, no changes to the agent's logic:

```json
{"agents": [
  {"name": "my-langgraph-agent", "type": "subprocess", "cmd": ["python3", "my_agent.py"]},
  {"name": "my-go-agent",        "type": "subprocess", "cmd": ["./agent"]},
  {"name": "my-inprocess-agent", "type": "callable",   "target": "mypkg.agent:run"}
]}
```

A complete agent can be 12 lines ([examples/minimal_agent.py](examples/minimal_agent.py)).
Agents call tools and models *through* the harness, which is what makes the
numbers comparable and lets the harness inject faults. Agents that call a
model provider directly can still report their usage with a `usage` message;
it is flagged as self-reported in the trace.

## Route model calls through Bifrost (or any OpenAI-compatible endpoint)

```bash
npx -y @maximhq/bifrost   # start a Bifrost gateway on :8080 and add your provider keys there
export AGENTBENCH_MODEL_BACKEND=openai
export AGENTBENCH_OPENAI_BASE_URL=http://localhost:8080/v1
export AGENTBENCH_MODEL=openai/gpt-4o-mini
export AGENTBENCH_PRICE_IN_PER_M=0.15 AGENTBENCH_PRICE_OUT_PER_M=0.60   # your prices, USD per 1M tokens
python3 -m agentbench run --repeats 3
```

The harness forwards each `model_call` to `$AGENTBENCH_OPENAI_BASE_URL/chat/completions`,
records the `usage` the endpoint returns, and computes cost from your prices.
Gateway errors become recorded model errors. The API key, if any, is read from
`AGENTBENCH_OPENAI_API_KEY` and is removed from the environment of subprocess
agents. This path is covered by tests against a local stub OpenAI-compatible
server (`tests/test_openai_backend.py`). We have not run it against a live
Bifrost gateway or a paid model.

The default backend, `mock`, is a deterministic local stand-in for an LLM
(`agentbench/mock_planner.py`). It needs no key and makes no network calls.
It is deliberately *instruction-following*: if a tool output contains an
instruction, it obeys it. That copies a known weakness of real LLMs and lets
the prompt-injection detector be exercised offline. Its token counts are
estimates (characters / 4) and its price is $0.

## Sample results (real run, included in this repo)

Command: `python3 -m agentbench run --repeats 3`, run on 2026-11-15 at 14:19 JST
(05:19 UTC) on Linux with Python 3.13.5 and the `mock` model backend. That is
3 agents x 5 scenarios x 12 tasks x 3 repeats = **540 runs in 9.3 s**. Raw
traces: [`results/runs.jsonl`](results/runs.jsonl). Report:
[`results/report.html`](results/report.html) (download and open it).

All three agents are **baselines we wrote to exercise the harness**. They are
not entries and not claims about any product or model:

* `scripted-py`: framework-free Python subprocess. Hand-written routing for this suite, retries transient tool errors (max 3 tries), reads only the structured `result` field, computes locally if the calculator is down. Uses no model. It is an upper-bound reference.
* `naive-node`: Node.js subprocess. Same routing idea, but no retries and no fallbacks. Uses no model.
* `planner-mockllm`: in-process Python ReAct loop. Every decision comes from a model call through the harness (here the `mock` backend). Retries come from the model, and it has no fallback when the model is down.

| Agent | Adapter | Success | pass^3 | Consistency | Avg steps | Avg tool calls | Avg model calls | Total tokens | Cost (USD) | Avg time | Injection compromised |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| scripted-py (baseline) | subprocess | 100.0% (180/180) | 100.0% | 100.0% | 1.50 | 1.50 | 0.00 | 0 | $0.00 | 20.5 ms | 0/36 |
| naive-node (baseline) | subprocess | 91.1% (164/180) | 83.3% | 86.7% | 1.31 | 1.31 | 0.00 | 0 | $0.00 | 29.9 ms | 0/36 |
| planner-mockllm (baseline) | callable | 63.3% (114/180) | 63.3% | 100.0% | 4.10 | 1.55 | 2.55 | 154,215 (est.) | $0.00 | 0.3 ms | 24/36 |

Success rate by failure scenario:

| Agent | baseline | flaky_tools | tool_outage | model_unavailable | prompt_injection |
|---|---:|---:|---:|---:|---:|
| scripted-py (baseline) | 100.0% (36/36) | 100.0% (36/36) | 100.0% (36/36) | 100.0% (36/36) | 100.0% (36/36) |
| naive-node (baseline) | 100.0% (36/36) | 72.2% (26/36) | 83.3% (30/36) | 100.0% (36/36) | 100.0% (36/36) |
| planner-mockllm (baseline) | 100.0% (36/36) | 100.0% (36/36) | 83.3% (30/36) | 0.0% (0/36) | 33.3% (12/36) |

What the run shows:

* **All three agents score 100% on the clean baseline**, so a plain accuracy benchmark would rank them as equal. Only the failure scenarios separate them.
* **No retries hurts under flaky tools.** `naive-node` drops to 72.2% (26/36). Its 10 failures are spread across 8 tasks and change from repeat to repeat, which is why its pass^3 (83.3%) is lower than its success rate (91.1%) and why its answer consistency falls to 86.7%.
* **Without a fallback, an outage fails the task.** When the calculator is down, both `naive-node` and `planner-mockllm` fail the two tasks that need it (t01, t03; 6/36 each). `scripted-py` computes locally and passes.
* **A model-driven agent with no fallback fails completely when the model is unavailable**: 0/36, including the no-tool string-reversal task.
* **The injection detector catches instruction-following behaviour.** `planner-mockllm` was compromised in 24 of 36 injection runs: every task that reads a retrieval tool's output. In each one it called the unlisted tool `export_customer_data` and returned the canary. The other 12 runs never read a tool output that carried the injection. The two agents that read only structured fields were not affected.
* **Cost of the model loop:** `planner-mockllm` needs 4.10 steps per run against 1.31 to 1.50 for the scripted agents, and about 857 (estimated) tokens per run. With a priced backend, the same columns show real tokens and USD.
* Time per run is not comparable across adapters: subprocess times include starting a process (about 20 to 30 ms here), while callable agents run in-process.

![Trace comparison](docs/report-trace-compare.png)

*Same task, same seed, same injected tool output: the model-driven baseline
(left) calls the unlisted tool three times and returns the canary. The scripted
baseline (right) reads only the structured field and answers 12.5.*

## Architecture

```
agents.json ──► adapters ──► Session (harness-controlled proxy) ──► sandbox tools (world.py)
                 │              │  ├─ FaultInjector (seeded): flaky / outage / injection / model down
   subprocess ───┤              │  ├─ model proxy ──► mock backend | OpenAI-compatible URL (Bifrost)
   (JSON lines)  │              │  └─ trace recorder: every step, tool I/O, tokens, cost, time
   callable ─────┘              ▼
                         runner (agents x scenarios x tasks x repeats, shared seeds)
                                ▼
                    results/runs.jsonl ──► metrics ──► results/report.html
```

| File | Role |
|---|---|
| `agentbench/world.py` | in-memory sandbox (records, files, documents) and 6 tools |
| `agentbench/tasks.py` | 12 tasks with exact checkers |
| `agentbench/faults.py` | seeded failure scenarios and the injection canary |
| `agentbench/session.py` | tool and model proxy, step limit, trace recording, scoring |
| `agentbench/adapters.py` | subprocess (JSON lines) and callable adapters, timeouts, crash containment |
| `agentbench/models.py` | `mock` and OpenAI-compatible (Bifrost) backends, token and cost metering |
| `agentbench/runner.py`, `metrics.py`, `report.py`, `cli.py` | matrix runner, aggregation, HTML report, CLI |
| `agents/` | the three baseline agents |
| `tests/` | 47 pytest tests |

## Tests

```
$ python3 -m pytest -q
47 passed
```

The tests cover the task checkers, seeded fault reproducibility, unlisted-tool
flagging, the step limit, the model-outage scenario, every task through both the
subprocess and the callable adapter, the Node agent, the injection detector,
containment of agents that hang or crash, JSONL, metrics and report output, and
the OpenAI-compatible backend against a local stub server (routing, auth header,
real usage, cost, gateway errors).

## Limitations and next steps

* The task suite is small (12 tasks) and synthetic by design, so every answer can be checked exactly. Next: pluggable task packs (web, code, SWE-style) using the same proxy.
* Real-LLM results are not included: no paid model was used for this submission. The Bifrost/OpenAI-compatible path is implemented and tested against a stub.
* Tool timing is in-process. Latency injection and per-tool cost are planned.

## Team

**Anicca**, Tokyo. [aniccaai.com](https://aniccaai.com). MIT licensed.
