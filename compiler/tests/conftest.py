"""Shared fixtures: a local stand-in for the Qwen API and helpers to build messy files."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MockQwen:
    """Replies from a queue. An entry is a dict (plan) or a (status, body) tuple."""

    def __init__(self):
        self.replies = []
        self.requests = []
        self.headers = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                mock.requests.append(body)
                mock.headers.append(dict(self.headers))
                reply = mock.replies.pop(0) if mock.replies else (500, "queue empty")
                if isinstance(reply, tuple):
                    status, text = reply
                else:
                    status, text = 200, json.dumps({
                        "choices": [{"message": {"content": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                    })
                data = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


@pytest.fixture
def qwen(monkeypatch):
    mock = MockQwen()
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_BASE_URL", mock.url)
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    monkeypatch.setattr("time.sleep", lambda *_: None)
    yield mock
    mock.stop()


@pytest.fixture
def no_key(monkeypatch):
    for name in ("QWEN_API_KEY", "DASHSCOPE_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path):
    for name in ("input", "template", "output"):
        (tmp_path / name).mkdir()
    return tmp_path


def cli_args(repo, *extra):
    return [
        "--input", str(repo / "input"),
        "--template-dir", str(repo / "template"),
        "--output", str(repo / "output"),
        *extra,
    ]
