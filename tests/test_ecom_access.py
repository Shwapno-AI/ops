"""Private E-commerce HTTP access tests; all responses contain synthetic data only."""
import hashlib
import http.client
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("ecom_server", Path(__file__).resolve().parents[1] / "scripts/ecom/server.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.snapshot = Path(self.work.name) / "ecom.json"
        self.snapshot.write_text('{"synthetic":true}')
        self.server = m.EcomServer(("127.0.0.1", 0), self.snapshot, "synthetic-test-password")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.work.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        h = dict(headers or {})
        if body is not None:
            body = json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result

    def login(self):
        status, headers, _ = self.request("POST", "/api/ecom/session", {"password": "synthetic-test-password"})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0], headers

    def test_unauthenticated_data_and_session_are_denied(self):
        for method in ("GET", "HEAD"):
            for path in ("/data/ecom.json", "/api/ecom/session"):
                status, headers, body = self.request(method, path)
                self.assertEqual(status, 401)
                self.assertNotIn(b"synthetic", body)
                self.assertIn("no-store", headers["Cache-Control"])

    def test_login_cookie_and_data_access(self):
        cookie, headers = self.login()
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, headers["Set-Cookie"])
        for path in ("/data/ecom.json", "/api/ecom/session"):
            status, headers, body = self.request("GET", path, headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(json.loads(body), {"authenticated": True})

    def test_wrong_forged_and_expired_credentials_cannot_read_data(self):
        self.assertEqual(self.request("POST", "/api/ecom/session", {"password": "wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/data/ecom.json", headers={"Cookie": m.COOKIE + "=forged"})[0], 401)
        cookie, _ = self.login()
        token = cookie.split("=", 1)[1]
        self.server.sessions[hashlib.sha256(token.encode()).digest()] = time.time() - 1
        self.assertEqual(self.request("GET", "/data/ecom.json", headers={"Cookie": cookie})[0], 401)

    def test_logout_revokes_the_server_session(self):
        cookie, _ = self.login()
        status, headers, _ = self.request("POST", "/api/ecom/logout", headers={"Cookie": cookie})
        self.assertEqual(status, 204)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/data/ecom.json", headers={"Cookie": cookie})[0], 401)

    def test_missing_configuration_and_snapshot_fail_closed(self):
        self.server.password = b""
        self.assertEqual(self.request("GET", "/data/ecom.json")[0], 503)
        self.assertEqual(self.request("POST", "/api/ecom/session", {"password": ""})[0], 503)
        self.server.password = b"synthetic-test-password"
        cookie, _ = self.login()
        self.snapshot.unlink()
        self.assertEqual(self.request("GET", "/data/ecom.json", headers={"Cookie": cookie})[0], 503)

    def test_cross_origin_login_and_logout_are_rejected(self):
        for path in ("/api/ecom/session", "/api/ecom/logout"):
            self.assertEqual(self.request("POST", path, {"password": "synthetic-test-password"}, {"Origin": "https://unrelated.invalid"})[0], 403)

    def test_brute_force_is_throttled(self):
        for _ in range(5):
            self.assertEqual(self.request("POST", "/api/ecom/session", {"password": "wrong"})[0], 401)
        self.assertEqual(self.request("POST", "/api/ecom/session", {"password": "wrong"})[0], 429)

    def test_unrelated_paths_and_invalid_body_types_are_rejected(self):
        self.assertEqual(self.request("GET", "/private/ecom.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/ecom/session", {"password": "x"}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/ecom/session", ["invalid"])[0], 401)
        self.assertEqual(self.request("POST", "/api/ecom/session", {"password": "\ud800"})[0], 401)
