"""The OpenAI-compatible backend (e.g. a Bifrost gateway) against a local stub server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentbench.adapters import CallableAdapter
from agentbench.models import OpenAICompatBackend
from agentbench.session import Session
from agentbench.tasks import TASKS_BY_ID


class Stub(BaseHTTPRequestHandler):
    calls = []
    fail = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.calls.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if Stub.fail:
            self.send_response(503)
            self.end_headers()
            return
        user = [m for m in body["messages"] if m["role"] == "user"]
        done = any(m["content"].startswith("Observation:") for m in user)
        content = '{"action":"final","answer":"12.5"}' if done else '{"action":"tool","name":"lookup","args":{"key":"sku:A-102"}}'
        out = json.dumps({"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Stub.calls.clear()
    Stub.fail = False
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_routes_through_base_url_and_records_real_usage_and_cost(server):
    backend = OpenAICompatBackend(base_url=server, api_key="test-key", model="openai/gpt-4o-mini")
    backend.price_in, backend.price_out = 0.15, 0.60  # USD per 1M tokens, set by the user
    task = TASKS_BY_ID["t02_price"]
    res = CallableAdapter("planner", "agents.planner_agent:run").run(task, Session(task, "baseline", 1, backend))
    assert res["success"] and res["model_calls"] == 2
    assert res["prompt_tokens"] == 200 and res["completion_tokens"] == 20 and not res["tokens_estimated"]
    assert res["cost_usd"] == pytest.approx((200 * 0.15 + 20 * 0.60) / 1e6)
    assert Stub.calls[0]["path"] == "/v1/chat/completions"
    assert Stub.calls[0]["body"]["model"] == "openai/gpt-4o-mini"
    assert Stub.calls[0]["auth"] == "Bearer test-key"


def test_gateway_errors_become_model_errors(server):
    Stub.fail = True
    task = TASKS_BY_ID["t02_price"]
    res = CallableAdapter("planner", "agents.planner_agent:run").run(task, Session(task, "baseline", 1, OpenAICompatBackend(base_url=server, api_key="")))
    assert not res["success"] and res["model_errors"] == 1
