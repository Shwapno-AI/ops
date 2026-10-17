#!/usr/bin/env python3
"""Serve private E-commerce data with revocable, server-validated sessions."""
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time
from collections import deque
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

COOKIE = "ops_ecom_session"
TTL = 8 * 60 * 60


class EcomServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, snapshot, password, secure=True):
        super().__init__(address, Handler)
        self.snapshot = Path(snapshot)
        self.password = password.encode("utf-8")
        self.secure_cookie = secure
        self.sessions = {}
        self.attempts = {}
        self.state_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "Ecommerce"
    sys_version = ""

    def log_message(self, *_args):
        pass  # Never log credentials, cookies, or private responses.

    def cookie(self, token="", age=0):
        return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}" + ("; Secure" if self.server.secure_cookie else "")

    def token_key(self):
        try:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            value = jar[COOKIE].value if COOKIE in jar else ""
        except CookieError:
            value = ""
        return hashlib.sha256(value.encode()).digest()

    def authorized(self):
        if not self.server.password:
            return False
        with self.server.state_lock:
            expiry = self.server.sessions.get(self.token_key(), 0)
        return expiry > time.time()

    def headers_for(self, status, length, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Vary", "Cookie")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def reply(self, status, body=None, cookie=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.headers_for(status, len(raw), cookie)
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path not in ("/api/ecom/session", "/data/ecom.json"):
            return self.reply(404)
        if not self.server.password:
            return self.reply(503, {"error": "E-commerce access is not configured."})
        if not self.authorized():
            return self.reply(401, {"error": "Sign in to E-commerce."})
        if path == "/api/ecom/session":
            return self.reply(200, {"authenticated": True})
        try:
            stream = self.server.snapshot.open("rb")
        except OSError:
            return self.reply(503, {"error": "E-commerce data is not ready. Try again later."})
        with stream:
            self.headers_for(200, os.fstat(stream.fileno()).st_size)
            if self.command != "HEAD":
                shutil.copyfileobj(stream, self.wfile)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/ecom/session", "/api/ecom/logout"):
            return self.reply(404)
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.reply(403, {"error": "Request origin is not allowed."})
        if path == "/api/ecom/logout":
            with self.server.state_lock:
                self.server.sessions.pop(self.token_key(), None)
            return self.reply(204, cookie=self.cookie())
        if not self.server.password:
            return self.reply(503, {"error": "E-commerce access is not configured."})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400)
        if not 0 < length <= 4096:
            return self.reply(413)
        # X-Real-IP is overwritten by the local nginx proxy, never trusted from the public client.
        address = self.headers.get("X-Real-IP") or self.client_address[0]
        now = time.time()
        with self.server.state_lock:
            self.server.attempts = {ip: q for ip, q in self.server.attempts.items() if q and q[-1] > now - 60}
            if address not in self.server.attempts and len(self.server.attempts) >= 2048:
                return self.reply(429, {"error": "Too many attempts. Try again shortly."})
            attempts = self.server.attempts.setdefault(address, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 5:
                return self.reply(429, {"error": "Too many attempts. Try again shortly."})
            attempts.append(now)
        try:
            body = json.loads(self.rfile.read(length))
            password = body.get("password") if isinstance(body, dict) else None
        except (ValueError, UnicodeError):
            password = None
        try:
            encoded = password.encode("utf-8") if isinstance(password, str) else b""
        except UnicodeError:
            encoded = b""
        if not encoded or not hmac.compare_digest(encoded, self.server.password):
            return self.reply(401, {"error": "Wrong password."})
        token = secrets.token_urlsafe(32)
        with self.server.state_lock:
            self.server.sessions = {key: exp for key, exp in self.server.sessions.items() if exp > now}
            if len(self.server.sessions) >= 2048:
                return self.reply(503, {"error": "Please try again shortly."})
            self.server.sessions.pop(self.token_key(), None)
            self.server.sessions[hashlib.sha256(token.encode()).digest()] = now + TTL
            self.server.attempts.pop(address, None)
        self.reply(200, {"authenticated": True}, self.cookie(token, TTL))


def main():
    snapshot = os.environ.get("ECOM_OUT") or Path(__file__).resolve().parents[2] / "private" / "ecom.json"
    password = os.environ.get("ECOM_PASSWORD") or os.environ.get("BASIC_AUTH_PASSWORD", "")
    server = EcomServer(("127.0.0.1", 8091), snapshot, password,
                        secure=os.environ.get("ECOM_COOKIE_SECURE", "1") != "0")
    server.serve_forever()


if __name__ == "__main__":
    main()
