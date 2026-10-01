"""A real local HTTP server speaking the OpenAI, Ollama and Anthropic streaming wire formats.
Adapters are exercised over real sockets; only the model itself is replaced."""
from __future__ import annotations

import collections
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORDS = ["Hello", " from", " the", " stub", " model."]


class StubLLM:
    def __init__(self, require_key: str | None = None) -> None:
        self.hits: collections.Counter = collections.Counter()
        self.bodies: list[dict] = []
        self.require_key = require_key
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):  # quiet
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _authed(self):
                if not stub.require_key:
                    return True
                ok = self.headers.get("Authorization") == f"Bearer {stub.require_key}" or self.headers.get("x-api-key") == stub.require_key
                if not ok:
                    self._json(401, {"error": "bad key"})
                return ok

            def do_GET(self):
                stub.hits[self.path] += 1
                if not self._authed():
                    return
                if self.path in ("/v1/models",):
                    self._json(200, {"data": [{"id": "stub-model"}, {"id": "slow"}]})
                elif self.path == "/api/tags":
                    self._json(200, {"models": [{"name": "stub-model:latest"}]})
                else:
                    self._json(404, {"error": "nope"})

            def _stream(self, chunks, ctype="text/event-stream", delay=0.01):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                try:
                    for c in chunks:
                        self.wfile.write(c.encode())
                        self.wfile.flush()
                        time.sleep(delay)
                except (BrokenPipeError, ConnectionResetError):
                    stub.hits["client_closed"] += 1

            def do_POST(self):
                stub.hits[self.path] += 1
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                stub.bodies.append(body)
                if not self._authed():
                    return
                model = body.get("model")
                if model == "broken":
                    self._json(500, {"error": "model crashed"})
                    return
                words = ["tick "] * 60 if model == "slow" else WORDS
                delay = 0.1 if model == "slow" else 0.01
                if self.path == "/v1/chat/completions":
                    ch = [f"data: {json.dumps({'choices': [{'delta': {'content': w}}]})}\n\n" for w in words]
                    ch.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': len(words)}})}\n\n")
                    ch.append("data: [DONE]\n\n")
                    self._stream(ch, delay=delay)
                elif self.path == "/api/chat":
                    ch = [json.dumps({"message": {"content": w}, "done": False}) + "\n" for w in words]
                    ch.append(json.dumps({"done": True, "eval_count": len(words), "prompt_eval_count": 9, "eval_duration": 250_000_000}) + "\n")
                    self._stream(ch, "application/x-ndjson", delay)
                elif self.path == "/v1/messages":
                    ch = [f"data: {json.dumps({'type': 'message_start', 'message': {'usage': {'input_tokens': 7}}})}\n\n"]
                    ch += [f"data: {json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': w}})}\n\n" for w in words]
                    ch += [f"data: {json.dumps({'type': 'message_delta', 'usage': {'output_tokens': len(words)}})}\n\n",
                           f"data: {json.dumps({'type': 'message_stop'})}\n\n"]
                    self._stream(ch, delay=delay)
                else:
                    self._json(404, {"error": "nope"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
