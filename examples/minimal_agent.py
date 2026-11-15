import json, sys
def send(o): print(json.dumps(o), flush=True)
def recv(): return json.loads(sys.stdin.readline())
task = recv()
send({"type": "tool_call", "id": 1, "name": "lookup", "args": {"key": "sku:A-102"}})
r = recv()
answer = str(r["output"]["result"]["unit_price"]) if r["ok"] else None
send({"type": "final", "answer": answer})
