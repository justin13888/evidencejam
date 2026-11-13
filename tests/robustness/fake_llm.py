"""Local OpenAI-compatible server that misbehaves on demand (judging-day failure modes)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ("ok", "http500", "http429", "http400_extras", "timeout", "garbage", "fenced", "think", "truncated",
         "wrong_ids", "empty_choices", "html")  # fmt: skip


def reply_for(mode: str, body: dict) -> tuple[int, str]:
    user = body["messages"][-1]["content"]
    ids = [json.loads(line)["id"] for line in user.replace(" /no_think", "").splitlines() if line.startswith("{")]
    payload = json.dumps({i: {"ok": True} for i in ids})
    content = {
        "ok": payload,
        "fenced": f"```json\n{payload}\n```",
        "think": f"<think>reasoning...</think>{payload}",
        "truncated": payload[: len(payload) // 2],
        "wrong_ids": json.dumps({"nope": 1}),
        "garbage": "I cannot help with that.",
    }.get(mode, payload)
    if mode == "empty_choices":
        return 200, json.dumps({"choices": []})
    if mode == "html":
        return 200, "<html>proxy error</html>"
    return 200, json.dumps({"choices": [{"message": {"content": content}}],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10}})  # fmt: skip


class FakeLLM:
    def __init__(self, mode: str = "ok"):
        self.mode, self.requests = mode, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                m = outer.mode
                if m == "timeout":
                    time.sleep(3)
                if m in ("http500", "http429") or (m == "http400_extras" and "chat_template_kwargs" in body):
                    code = {"http500": 500, "http429": 429}.get(m, 400)
                    self.send_response(code)
                    self.end_headers()
                    return
                code, text = reply_for(m, body)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(text.encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
