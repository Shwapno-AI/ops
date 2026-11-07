"""The website: sign in, upload, compile, download."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from excelcompiler import __version__
from excelcompiler.qwen import DEFAULT_MODEL, QwenClient, QwenError

from .jobs import ROOT, JobError, JobStore, ResyncNeeded

CHUNK_BYTES = 8 * 1024 * 1024
MAX_LOGIN_FAILURES = 10
LOCKOUT_SECONDS = 600
SAMPLE_INSTRUCTION = "Add up January and February for each outlet, include the Zone, and sort by sales, highest first."


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        return default


def _secret_key(data_dir: Path) -> str:
    path = data_dir / ".secret_key"
    try:
        return path.read_text().strip()
    except OSError:
        key = secrets.token_hex(32)
        path.write_text(key)
        path.chmod(0o600)
        return key


def create_app(data_dir: str | None = None, start_threads: bool = True) -> Flask:
    logging.basicConfig(level=logging.INFO)
    data = Path(data_dir or os.getenv("DATA_DIR") or "/data")
    data.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        SECRET_KEY=_secret_key(data),
        MAX_CONTENT_LENGTH=2 * CHUNK_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=30 * 86400,
    )
    store = JobStore(data, _env_int("MAX_UPLOAD_MB", 2048), _env_int("RETENTION_DAYS", 7), _env_int("JOB_TIMEOUT_MIN", 120))
    app.extensions["jobs"] = store
    store.recover()
    if start_threads:
        store.start_threads()

    failures: dict[str, tuple[int, float]] = {}
    failures_lock = threading.Lock()

    def password() -> str:
        return os.getenv("APP_PASSWORD") or ""

    def open_access() -> bool:
        return os.getenv("ALLOW_NO_PASSWORD", "").strip().lower() == "true"

    def password_tag() -> str:
        return hashlib.sha256(password().encode()).hexdigest()

    def signed_in() -> bool:
        if not password():
            return open_access()
        return hmac.compare_digest(session.get("tag", ""), password_tag())

    @app.before_request
    def guard():
        app.config["SESSION_COOKIE_SECURE"] = request.is_secure
        if request.endpoint in ("healthz", "login", "static") or signed_in():
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Please sign in again."), 401
        return redirect(url_for("login"))

    # FRAME_ANCESTORS lets named sites show the app inside their page, e.g. "https://ops.shwapno.app" for the
    # Operations dashboard; space-separated https origins only. Unset, no site may frame it.
    ancestors = " ".join(o for o in (os.getenv("FRAME_ANCESTORS") or "").split() if o.startswith("https://") and "'" not in o and ";" not in o)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not ancestors:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        framers = ancestors or "'none'"
        response.headers["Content-Security-Policy"] = f"default-src 'self'; img-src 'self' data:; frame-ancestors {framers}; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(JobError)
    def job_error(exc: JobError):
        return jsonify(error=str(exc)), exc.status

    @app.errorhandler(ResyncNeeded)
    def resync(exc: ResyncNeeded):
        return jsonify(error="resync", size=exc.size), 409

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return jsonify(error="That upload piece is too large."), 413

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=exc.description), exc.code
        return exc

    # ---------------- pages ----------------
    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not password() and not open_access():
            return render_template("login.html", version=__version__, setup=True), 503
        if signed_in():
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("login.html", version=__version__)
        address = request.remote_addr or "?"
        with failures_lock:
            count, since = failures.get(address, (0, 0.0))
            if count >= MAX_LOGIN_FAILURES and time.time() - since < LOCKOUT_SECONDS:
                return render_template("login.html", version=__version__, error="Too many tries. Wait 10 minutes and try again."), 429
        if hmac.compare_digest(request.form.get("password", "").encode(), password().encode()):
            with failures_lock:
                failures.pop(address, None)
            session.permanent = True
            session["tag"] = password_tag()
            return redirect(url_for("index"))
        with failures_lock:
            count, since = failures.get(address, (0, 0.0))
            if time.time() - since >= LOCKOUT_SECONDS:
                count, since = 0, time.time()
            failures[address] = (count + 1, since)
        time.sleep(0.5)
        return render_template("login.html", version=__version__, error="That password is not right."), 401

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        return render_template("index.html", version=__version__, can_logout=bool(password()))

    # ---------------- api ----------------
    @app.get("/api/status")
    def status():
        client = QwenClient.from_env()
        usage = shutil.disk_usage(data)
        return jsonify(
            qwen_ready=client is not None,
            model=client.model if client else (os.getenv("QWEN_MODEL") or DEFAULT_MODEL),
            storage_kept=os.path.ismount(data),
            free_gb=round(usage.free / 1024**3, 1),
            max_upload_mb=store.max_upload // (1024 * 1024),
            retention_days=store.retention_days,
            chunk_bytes=CHUNK_BYTES,
        )

    @app.post("/api/qwen-test")
    def qwen_test():
        client = QwenClient.from_env()
        if client is None:
            return jsonify(ok=False, error="QWEN_API_KEY is not set in Coolify.")
        client.attempts, client.timeout = 1, 45
        started = time.time()
        try:
            client.chat([{"role": "user", "content": 'Reply with this JSON only: {"ok": true}'}])
        except QwenError as exc:
            return jsonify(ok=False, error=str(exc)[:500])
        return jsonify(ok=True, model=client.model, seconds=round(time.time() - started, 1))

    @app.get("/api/jobs")
    def list_jobs():
        return jsonify(jobs=[store.summary(job) for job in store.list()])

    @app.post("/api/jobs")
    def new_job():
        return jsonify(id=store.create()["id"]), 201

    @app.put("/api/jobs/<job_id>/chunk")
    def chunk(job_id: str):
        try:
            offset = int(request.args.get("offset", ""))
        except ValueError:
            raise JobError("Bad upload request.") from None
        size = store.write_chunk(job_id, request.args.get("kind", ""), request.args.get("name", ""), offset, request.stream)
        return jsonify(size=size)

    @app.post("/api/jobs/<job_id>/start")
    def start(job_id: str):
        body = request.get_json(silent=True) or {}
        job = store.start(job_id, body.get("files") or [], str(body.get("instruction") or ""))
        return jsonify(store.result(job))

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        return jsonify(store.result(store.load(job_id)))

    @app.post("/api/jobs/<job_id>/rerun")
    def rerun(job_id: str):
        body = request.get_json(silent=True) or {}
        return jsonify(store.result(store.rerun(job_id, str(body.get("instruction") or ""))))

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id: str):
        return jsonify(store.result(store.cancel(job_id)))

    @app.delete("/api/jobs/<job_id>")
    def delete(job_id: str):
        store.delete(job_id)
        return jsonify(ok=True)

    @app.get("/api/jobs/<job_id>/download/<path:name>")
    def download(job_id: str, name: str):
        store.load(job_id)
        folder = store.folder(job_id) / "output"
        if name == "report.json":
            raise JobError("That file does not exist.", 404)
        return send_from_directory(folder, name, as_attachment=True)

    @app.post("/api/sample")
    def sample():
        body = request.get_json(silent=True) or {}
        examples = ROOT / "examples"
        template = next((examples / "template").glob("*.xlsx"), None) if body.get("template") else None
        instruction = SAMPLE_INSTRUCTION if QwenClient.from_env() else ""
        return jsonify(store.result(store.from_folder(examples / "input", template, instruction)))

    return app
