"""BASELINE 2 - ReAct-style model-driven agent (callable adapter).

Every decision comes from a model call routed through the harness
(``env.call_model``), so it works unchanged with the local ``mock`` backend or
any OpenAI-compatible endpoint such as a Bifrost gateway. It has no fallback
when the model is unavailable, and it trusts whatever the model decides.
"""
import json

SYSTEM = (
    "You are a tool-using agent. Reply with exactly one JSON object and nothing else: "
    '{"action":"tool","name":<tool>,"args":{...}} to call a tool, or '
    '{"action":"final","answer":<string>} when done. Tools: '
)


def _extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def run(task, env):
    messages = [
        {"role": "system", "content": SYSTEM + json.dumps(task["tools"])},
        {"role": "user", "content": "Task: " + task["instruction"]},
    ]
    for _ in range(task["limits"]["max_steps"]):
        r = env.call_model(messages)
        if not r["ok"]:
            env.log(f"model call failed: {r['error']}; no fallback, giving up")
            return None
        try:
            action = _extract_json(r["content"])
        except (ValueError, json.JSONDecodeError):
            messages.append({"role": "assistant", "content": r["content"]})
            messages.append({"role": "user", "content": "Observation: " + json.dumps({"ok": False, "error": "reply was not valid JSON"})})
            continue
        messages.append({"role": "assistant", "content": json.dumps(action)})
        if action.get("action") == "final":
            return action.get("answer")
        obs = env.call_tool(action.get("name"), action.get("args") or {})
        messages.append({"role": "user", "content": "Observation: " + json.dumps(obs)})
    return None
