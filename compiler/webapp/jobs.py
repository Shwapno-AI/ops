"""Stores compile jobs on disk and runs them one at a time in a separate process."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_EXTENSIONS = {".xlsx", ".xlsm", ".xlsb", ".xls", ".ods", ".csv", ".tsv", ".txt"}
TEMPLATE_EXTENSIONS = {".xlsx", ".xlsm", ".xlsb", ".xls", ".ods"}
MAX_FILES = 300
MAX_INSTRUCTION = 4000
STAGES = ["reading", "planning", "writing", "checking"]
log = logging.getLogger("excel-compiler")


class JobError(Exception):
    """A problem to show the user. status is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def safe_name(name: str) -> str:
    """Keep a readable file name, in any language, with no way out of the job folder."""
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    if not name or name.startswith("~$"):
        raise JobError("That file name cannot be used.")
    stem, suffix = os.path.splitext(name)
    return stem[:160] + suffix[:10]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, data_dir: Path, max_upload_mb: int = 2048, retention_days: int = 7, timeout_minutes: int = 120):
        self.root = Path(data_dir) / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_upload = max_upload_mb * 1024 * 1024
        self.retention_days = retention_days
        self.timeout = timeout_minutes * 60
        self.lock = threading.RLock()
        self.pending: queue.Queue[str] = queue.Queue()
        self.process: tuple[str, subprocess.Popen] | None = None
        self.cancelled: set[str] = set()

    # ---------------- storage ----------------
    def folder(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id or ""):
            raise JobError("That job does not exist.", 404)
        return self.root / job_id

    def load(self, job_id: str) -> dict:
        path = self.folder(job_id) / "job.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise JobError("That job does not exist. Files are removed after a few days.", 404) from None

    def save(self, job: dict) -> None:
        path = self.folder(job["id"]) / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def update(self, job_id: str, **changes) -> dict:
        with self.lock:
            job = self.load(job_id)
            job.update(changes)
            self.save(job)
            return job

    def _new(self, instruction: str = "") -> dict:
        job = {
            "id": uuid.uuid4().hex,
            "status": "draft",
            "stage": None,
            "created": now_iso(),
            "started": None,
            "finished": None,
            "instruction": instruction,
            "files": [],
            "template": None,
            "error": None,
        }
        folder = self.folder(job["id"])
        for name in ("input", "template", "output"):
            (folder / name).mkdir(parents=True)
        self.save(job)
        return job

    def create(self) -> dict:
        return self._new()

    def result(self, job: dict) -> dict:
        """The job as the website needs it, with its report and queue position."""
        view = dict(job)
        path = self.folder(job["id"]) / "output" / "report.json"
        if job["status"] == "done" and path.exists():
            view["report"] = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] == "queued":
            ahead = [j for j in self.list(100) if j["status"] in ("queued", "running") and j["created"] < job["created"]]
            view["ahead"] = len(ahead)
        return view

    def list(self, limit: int = 30) -> list[dict]:
        jobs = []
        for folder in self.root.iterdir():
            try:
                job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if job.get("status") != "draft":
                jobs.append(job)
        jobs.sort(key=lambda j: j["created"], reverse=True)
        return jobs[:limit]

    def summary(self, job: dict) -> dict:
        view = {k: job.get(k) for k in ("id", "status", "created", "finished", "error", "instruction")}
        view["file_count"] = len(job["files"])
        view["first_file"] = job["files"][0]["name"] if job["files"] else None
        view["template"] = job["template"]["name"] if job.get("template") else None
        path = self.folder(job["id"]) / "output" / "report.json"
        if job["status"] == "done" and path.exists():
            report = json.loads(path.read_text(encoding="utf-8"))
            view["result"] = report["status"]
            view["output"] = report["output"]
        return view

    # ---------------- upload ----------------
    def _upload_size(self, job_id: str) -> int:
        folder = self.folder(job_id)
        return sum(p.stat().st_size for kind in ("input", "template") for p in (folder / kind).glob("*") if p.is_file())

    def write_chunk(self, job_id: str, kind: str, name: str, offset: int, stream) -> int:
        """Append one piece of a file. Safe to retry: a repeated piece overwrites itself."""
        job = self.load(job_id)
        if job["status"] != "draft":
            raise JobError("This job has already started.", 409)
        if kind not in ("input", "template"):
            raise JobError("Unknown file type.")
        name = safe_name(name)
        allowed = INPUT_EXTENSIONS if kind == "input" else TEMPLATE_EXTENSIONS
        if os.path.splitext(name)[1].lower() not in allowed:
            raise JobError(f"{name} is not a supported file type. Use {', '.join(sorted(allowed))}.")
        path = self.folder(job_id) / kind / name
        current = path.stat().st_size if path.exists() else 0
        if offset < 0 or offset > current:
            raise ResyncNeeded(current)
        if not path.exists() and len(list(path.parent.iterdir())) >= (MAX_FILES if kind == "input" else 1):
            raise JobError("Too many files." if kind == "input" else "Use one template file.")
        written = self._upload_size(job_id) - (current - offset)
        try:
            with open(path, "r+b" if path.exists() else "wb") as handle:
                handle.seek(offset)
                handle.truncate(offset)
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > self.max_upload:
                        raise JobError(f"These files are over the {self.max_upload // (1024 * 1024):,} MB limit.", 413)
                    handle.write(block)
                return handle.tell()
        except OSError as exc:
            if exc.errno == 28:
                raise JobError("The server is out of disk space. Delete old results or free up space.", 507) from None
            raise

    def start(self, job_id: str, files: list[dict], instruction: str) -> dict:
        with self.lock:
            job = self.load(job_id)
            if job["status"] != "draft":
                raise JobError("This job has already started.", 409)
            folder = self.folder(job_id)
            names = {"input": [], "template": []}
            for item in files:
                kind, name, size = item.get("kind"), safe_name(item.get("name", "")), item.get("size")
                if kind not in names:
                    raise JobError("Unknown file type.")
                path = folder / kind / name
                if not path.exists() or path.stat().st_size != size:
                    raise JobError(f"{name} did not upload completely. Please try again.", 409)
                names[kind].append({"name": name, "size": size})
            if not names["input"]:
                raise JobError("Add at least one source file.")
            if len(names["template"]) > 1:
                raise JobError("Use one template file.")
            job.update(files=names["input"], template=names["template"][0] if names["template"] else None)
            return self._enqueue(job, instruction)

    def _enqueue(self, job: dict, instruction: str) -> dict:
        if len(instruction) > MAX_INSTRUCTION:
            raise JobError(f"The instruction is too long; keep it under {MAX_INSTRUCTION:,} characters.")
        job.update(status="queued", instruction=instruction.strip())
        self.save(job)
        self.pending.put(job["id"])
        return job

    def rerun(self, job_id: str, instruction: str) -> dict:
        """Run the same files again, usually with a corrected instruction."""
        with self.lock:
            old = self.load(job_id)
            if old["status"] in ("draft", "queued", "running"):
                raise JobError("This job has not finished yet.", 409)
            job = self._new()
            source, target = self.folder(job_id), self.folder(job["id"])
            for kind in ("input", "template"):
                for path in (source / kind).iterdir():
                    try:
                        os.link(path, target / kind / path.name)
                    except OSError:
                        shutil.copy2(path, target / kind / path.name)
            job.update(files=old["files"], template=old["template"])
            return self._enqueue(job, instruction)

    def from_folder(self, inputs: Path, template: Path | None, instruction: str) -> dict:
        """A job from files already on the server: the built-in sample files."""
        with self.lock:
            job = self._new()
            target = self.folder(job["id"])
            for path in sorted(inputs.iterdir()):
                shutil.copy2(path, target / "input" / path.name)
                job["files"].append({"name": path.name, "size": path.stat().st_size})
            if template:
                shutil.copy2(template, target / "template" / template.name)
                job["template"] = {"name": template.name, "size": template.stat().st_size}
            return self._enqueue(job, instruction)

    # ---------------- control ----------------
    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.load(job_id)
            if job["status"] == "queued":
                self.cancelled.add(job_id)
                return self.update(job_id, status="cancelled", finished=now_iso())
            if job["status"] == "running":
                self.cancelled.add(job_id)
                if self.process and self.process[0] == job_id:
                    _kill(self.process[1])
                return job
            raise JobError("This job is not running.", 409)

    def delete(self, job_id: str) -> None:
        with self.lock:
            job = self.load(job_id)
            if job["status"] in ("queued", "running"):
                raise JobError("Cancel this job before deleting it.", 409)
            shutil.rmtree(self.folder(job_id), ignore_errors=True)

    def recover(self) -> None:
        """After a restart, nothing is still running: say so instead of waiting forever."""
        for job in self.list(10_000):
            if job["status"] in ("queued", "running"):
                self.update(job["id"], status="failed", finished=now_iso(), error="The server restarted during this job. Click Run again.")

    def clean(self, now: float | None = None) -> int:
        """Remove finished jobs after the retention period and abandoned uploads after a day."""
        now = now or time.time()
        removed = 0
        for folder in list(self.root.iterdir()):
            try:
                job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
                created = dt.datetime.fromisoformat(job["created"]).timestamp()
            except (OSError, ValueError, KeyError):
                continue
            age_days = (now - created) / 86400
            if job["status"] in ("queued", "running"):
                continue
            if age_days > (1 if job["status"] == "draft" else self.retention_days):
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        return removed

    # ---------------- running ----------------
    def run_next(self, block: bool = True, timeout: float | None = None) -> bool:
        try:
            job_id = self.pending.get(block=block, timeout=timeout)
        except queue.Empty:
            return False
        try:
            if job_id in self.cancelled:
                self.cancelled.discard(job_id)
                return True
            self._run(job_id)
        except JobError:  # deleted while waiting
            pass
        except Exception:
            log.exception("Job %s crashed", job_id)
            self.update(job_id, status="failed", finished=now_iso(), error="Something went wrong on the server. Please try again.")
        return True

    def worker(self) -> None:
        while True:
            self.run_next()

    def janitor(self) -> None:
        while True:
            try:
                self.clean()
            except Exception:
                log.exception("Clean up failed")
            time.sleep(3600)

    def start_threads(self) -> None:
        threading.Thread(target=self.worker, name="compile-worker", daemon=True).start()
        threading.Thread(target=self.janitor, name="clean-up", daemon=True).start()

    def _run(self, job_id: str) -> None:
        job = self.update(job_id, status="running", stage="reading", started=now_iso())
        folder = self.folder(job_id)
        command = [sys.executable, "-m", "excelcompiler", "--input", str(folder / "input"), "--template-dir", str(folder / "template"), "--output", str(folder / "output")]
        if job["instruction"]:
            command += ["--instruction", job["instruction"]]
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        with self.lock:
            self.process = (job_id, process)
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            _kill(process)

        timer = threading.Timer(self.timeout, expire)
        timer.start()
        tail: deque[str] = deque(maxlen=40)
        try:
            with open(folder / "run.log", "w", encoding="utf-8") as logfile:
                for line in process.stdout:
                    line = line.rstrip()
                    logfile.write(line + "\n")
                    logfile.flush()
                    if line.startswith("@@stage "):
                        self.update(job_id, stage=line.split(" ", 1)[1])
                    else:
                        tail.append(line)
            code = process.wait()
        finally:
            timer.cancel()
            with self.lock:
                self.process = None

        if job_id in self.cancelled:
            self.cancelled.discard(job_id)
            self.update(job_id, status="cancelled", finished=now_iso(), stage=None)
        elif code in (0, 2):
            self.update(job_id, status="done", finished=now_iso(), stage=None)
        else:
            self.update(job_id, status="failed", finished=now_iso(), stage=None, error=self._explain(code, tail, timed_out.is_set()))

    def _explain(self, code: int, tail: deque, timed_out: bool) -> str:
        if timed_out:
            return f"This job went over the {self.timeout // 60}-minute limit and was stopped."
        if code == -signal.SIGKILL:
            return "The server ran out of memory on this job. Try fewer or smaller files, or give the app more memory in Coolify."
        for line in reversed(tail):
            if line.startswith("Error: "):
                return line[len("Error: "):]
        log.error("Job ended with code %s: %s", code, list(tail)[-5:])
        return "Something went wrong while compiling. The details are in the server log."


class ResyncNeeded(Exception):
    """The client's offset is ahead of what arrived; it should continue from `size`."""

    def __init__(self, size: int):
        super().__init__(str(size))
        self.size = size


def _kill(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
