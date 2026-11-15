# Agent protocol (JSON lines over stdin/stdout)

Any executable can be benchmarked without code changes to its logic: wrap its
I/O so it reads and writes one JSON object per line. The harness starts one
process per run.

## Harness -> agent

```json
{"type": "task", "task_id": "t02_price", "instruction": "What is the unit price ...", "tools": [{"name": "lookup", "description": "...", "parameters": {"key": "string"}}], "limits": {"max_steps": 15}}
{"type": "tool_result", "id": 1, "ok": true, "output": {"result": {"unit_price": 12.5}}}
{"type": "tool_result", "id": 2, "ok": false, "error": "TransientToolError: 503 Service Unavailable"}
{"type": "model_result", "id": 3, "ok": true, "content": "...", "usage": {"prompt_tokens": 120, "completion_tokens": 14}}
```

## Agent -> harness

| message | meaning |
|---|---|
| `{"type":"tool_call","id":1,"name":"lookup","args":{"key":"sku:A-102"}}` | call a tool through the harness proxy (recorded, may be fault-injected) |
| `{"type":"model_call","id":3,"messages":[...],"model":"optional"}` | call a model through the harness (recorded, token + cost metered, routed to the configured backend, e.g. Bifrost) |
| `{"type":"usage","prompt_tokens":..,"completion_tokens":..,"cost_usd":..,"model":".."}` | for agents that call models themselves: self-reported usage (flagged as self-reported in the trace) |
| `{"type":"log","message":"..."}` | free-text reasoning or notes shown in the trace viewer |
| `{"type":"final","answer":"12.5"}` | end of run |

Anything else printed to stdout is recorded as a non-protocol line and ignored.
Each `tool_call` and `model_call` is one **step**. Runs that exceed
`max_steps`, exceed the timeout, crash, or exit without `final` are recorded as
failures with the reason.

## Minimal agent (Python, 12 lines)

```python
import json, sys
def send(o): print(json.dumps(o), flush=True)
def recv(): return json.loads(sys.stdin.readline())
task = recv()
send({"type": "tool_call", "id": 1, "name": "lookup", "args": {"key": "sku:A-102"}})
r = recv()
answer = str(r["output"]["result"]["unit_price"]) if r["ok"] else None
send({"type": "final", "answer": answer})
```

## In-process Python agents

Register `{"type": "callable", "target": "package.module:function"}` where
`function(task: dict, env) -> answer` and `env` provides `call_tool(name, args)`,
`call_model(messages, model=None)`, `log(message)` and `report_usage(...)`.
A LangGraph / CrewAI / plain-Python agent only needs its tool and model clients
pointed at `env`.
