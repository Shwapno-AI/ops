import io
import json
import os
import time
from pathlib import Path

import pytest
from openpyxl import Workbook

from webapp.app import create_app
from webapp.jobs import JobError, JobStore, safe_name


def workbook_bytes(rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


SALES = workbook_bytes([["Outlet Code", "Sales"], ["D1", 100], ["D2", 200]])
FORM = workbook_bytes([["Outlet Code", "Sales", "Double"], [None, None, "=B2*2"]])


@pytest.fixture
def app(tmp_path, monkeypatch, no_key):
    monkeypatch.setenv("APP_PASSWORD", "open sesame")
    monkeypatch.delenv("ALLOW_NO_PASSWORD", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    return create_app(str(tmp_path), start_threads=False)


@pytest.fixture
def client(app):
    test_client = app.test_client()
    assert test_client.post("/login", data={"password": "open sesame"}).status_code == 302
    return test_client


def put(client, job_id, kind, name, data, offset=0):
    return client.put(f"/api/jobs/{job_id}/chunk", query_string={"kind": kind, "name": name, "offset": offset}, data=data)


def upload(client, files, template=None):
    job_id = client.post("/api/jobs").get_json()["id"]
    listed = []
    for name, data in files.items():
        assert put(client, job_id, "input", name, data).status_code == 200
        listed.append({"kind": "input", "name": name, "size": len(data)})
    if template:
        assert put(client, job_id, "template", "Form.xlsx", template).status_code == 200
        listed.append({"kind": "template", "name": "Form.xlsx", "size": len(template)})
    return job_id, listed


def start(client, job_id, listed, instruction=""):
    response = client.post(f"/api/jobs/{job_id}/start", json={"files": listed, "instruction": instruction})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def run_all(app):
    while app.extensions["jobs"].run_next(block=False):
        pass


def test_everything_needs_sign_in(app):
    guest = app.test_client()
    assert guest.get("/").status_code == 302
    assert guest.get("/api/jobs").status_code == 401
    assert guest.post("/api/jobs").status_code == 401
    assert guest.get("/healthz").status_code == 200
    assert guest.post("/login", data={"password": "wrong"}).status_code == 401
    assert guest.get("/api/jobs").status_code == 401


def test_no_password_means_no_entry(tmp_path, monkeypatch, no_key):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("ALLOW_NO_PASSWORD", raising=False)
    guest = create_app(str(tmp_path), start_threads=False).test_client()
    assert guest.get("/").status_code == 302
    page = guest.get("/login")
    assert page.status_code == 503 and b"APP_PASSWORD" in page.data
    assert guest.post("/api/jobs").status_code == 401


def test_too_many_wrong_passwords_lock_out(app, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    guest = app.test_client()
    for _ in range(10):
        assert guest.post("/login", data={"password": "nope"}).status_code == 401
    assert guest.post("/login", data={"password": "open sesame"}).status_code == 429


def test_changing_the_password_signs_everyone_out(client, monkeypatch):
    assert client.get("/api/jobs").status_code == 200
    monkeypatch.setenv("APP_PASSWORD", "new one")
    assert client.get("/api/jobs").status_code == 401


def test_security_headers(client):
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_framing_is_refused_unless_a_site_is_named(client, tmp_path, monkeypatch):
    headers = client.get("/").headers
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"
    monkeypatch.setenv("FRAME_ANCESTORS", "https://ops.shwapno.app http://plain.example 'self'; bad")
    framed = create_app(str(tmp_path / "framed"), start_threads=False).test_client()
    headers = framed.get("/login").headers
    assert "frame-ancestors https://ops.shwapno.app;" in headers["Content-Security-Policy"]
    assert "X-Frame-Options" not in headers


def test_upload_compile_download(app, client):
    job_id, listed = upload(client, {"বিক্রয় জানুয়ারি.xlsx": SALES})
    job = start(client, job_id, listed)
    assert job["status"] == "queued"
    run_all(app)
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "done"
    report = job["report"]
    assert report["results"][0]["rows"] == 2
    file = client.get(f"/api/jobs/{job_id}/download/{report['output']}")
    assert file.status_code == 200 and file.data[:2] == b"PK"
    assert b"Compile report" in client.get(f"/api/jobs/{job_id}/download/report.md").data
    assert client.get(f"/api/jobs/{job_id}/download/job.json").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/download/../job.json").status_code == 404
    listed_jobs = client.get("/api/jobs").get_json()["jobs"]
    assert listed_jobs[0]["output"] == report["output"] and listed_jobs[0]["result"] == "warn"


def test_template_job(app, client):
    job_id, listed = upload(client, {"s.xlsx": SALES}, template=FORM)
    start(client, job_id, listed)
    run_all(app)
    report = client.get(f"/api/jobs/{job_id}").get_json()["report"]
    assert report["template"] == "Form.xlsx" and report["output"].startswith("Form_")
    assert any(c["name"].endswith("saved totals") for c in report["passed"])


def test_large_file_arrives_in_pieces_and_retries_are_safe(app, client):
    job_id = client.post("/api/jobs").get_json()["id"]
    lines = "Outlet Code,Sales\n" + "".join(f"D{i},{i}\n" for i in range(50000))
    data = lines.encode()
    size = 64 * 1024
    offset = 0
    while offset < len(data):
        piece = data[offset : offset + size]
        assert put(client, job_id, "input", "big.csv", piece, offset).get_json()["size"] == offset + len(piece)
        # the same piece sent twice, as after a dropped connection
        assert put(client, job_id, "input", "big.csv", piece, offset).get_json()["size"] == offset + len(piece)
        offset += len(piece)
    start(client, job_id, [{"kind": "input", "name": "big.csv", "size": len(data)}])
    run_all(app)
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["report"]["results"][0]["rows"] == 50000


def test_a_skipped_piece_asks_the_browser_to_resync(client):
    job_id = client.post("/api/jobs").get_json()["id"]
    put(client, job_id, "input", "a.csv", b"12345")
    response = put(client, job_id, "input", "a.csv", b"x", offset=99)
    assert response.status_code == 409 and response.get_json() == {"error": "resync", "size": 5}


def test_an_incomplete_upload_cannot_start(client):
    job_id = client.post("/api/jobs").get_json()["id"]
    put(client, job_id, "input", "a.csv", b"12345")
    response = client.post(f"/api/jobs/{job_id}/start", json={"files": [{"kind": "input", "name": "a.csv", "size": 999}]})
    assert response.status_code == 409 and "did not upload completely" in response.get_json()["error"]
    assert client.post(f"/api/jobs/{job_id}/start", json={"files": []}).status_code == 400


def test_only_spreadsheets_are_accepted(client):
    job_id = client.post("/api/jobs").get_json()["id"]
    assert put(client, job_id, "input", "virus.exe", b"x").status_code == 400
    assert put(client, job_id, "template", "data.csv", b"x").status_code == 400
    assert put(client, job_id, "other", "a.csv", b"x").status_code == 400


def test_upload_limit(tmp_path, monkeypatch, no_key):
    monkeypatch.setenv("APP_PASSWORD", "x")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    client = create_app(str(tmp_path), start_threads=False).test_client()
    client.post("/login", data={"password": "x"})
    job_id = client.post("/api/jobs").get_json()["id"]
    response = put(client, job_id, "input", "a.csv", b"x" * (1024 * 1024 + 10))
    assert response.status_code == 413 and "limit" in response.get_json()["error"]


@pytest.mark.parametrize("name, expected", [
    ("../../etc/passwd.xlsx", "passwd.xlsx"),
    ("..\\..\\windows\\a.xlsx", "a.xlsx"),
    ("বিক্রয় জানুয়ারি.xlsx", "বিক্রয় জানুয়ারি.xlsx"),
    ("Kabir Zone Nov'26.xlsx", "Kabir Zone Nov'26.xlsx"),
    ('a<b>:c.xlsx', "a_b__c.xlsx"),
])
def test_file_names_stay_inside_the_job(name, expected):
    assert safe_name(name) == expected


@pytest.mark.parametrize("name", ["", "..", "~$lock.xlsx"])
def test_unusable_names(name):
    with pytest.raises(JobError):
        safe_name(name)


def test_bad_job_ids(client):
    assert client.get("/api/jobs/../../etc").status_code == 404
    assert client.get("/api/jobs/" + "a" * 32).status_code == 404
    assert client.get("/api/jobs/not-a-job/download/x").status_code == 404


def test_run_again_keeps_the_files_and_shows_the_real_error(app, client):
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed, instruction="keep only D1")
    run_all(app)
    failed = client.get(f"/api/jobs/{job_id}").get_json()
    assert failed["status"] == "failed" and "QWEN_API_KEY" in failed["error"]

    again = client.post(f"/api/jobs/{job_id}/rerun", json={"instruction": ""}).get_json()
    assert again["id"] != job_id and again["files"] == failed["files"]
    run_all(app)
    assert client.get(f"/api/jobs/{again['id']}").get_json()["status"] == "done"


def test_unreadable_file_shows_as_a_failed_check(app, client):
    job_id, listed = upload(client, {"good.xlsx": SALES, "bad.xlsx": b"PK\x03\x04junk"})
    start(client, job_id, listed)
    run_all(app)
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "done" and job["report"]["status"] == "fail"
    assert job["report"]["output"].endswith("_CHECK_FAILED.xlsx")


def test_cancel_and_delete(app, client):
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 409
    assert client.post(f"/api/jobs/{job_id}/cancel").get_json()["status"] == "cancelled"
    run_all(app)
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "cancelled"
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_a_running_job_can_be_stopped(app, client, monkeypatch):
    store = app.extensions["jobs"]
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed)
    real_popen = __import__("subprocess").Popen

    def slow(command, **kwargs):
        return real_popen(["sh", "-c", "echo '@@stage reading'; sleep 30"], **kwargs)

    monkeypatch.setattr("webapp.jobs.subprocess.Popen", slow)
    import threading

    thread = threading.Thread(target=store.run_next)
    thread.start()
    deadline = time.time() + 10
    while not store.process and time.time() < deadline:
        time.sleep(0.05)
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "running"
    client.post(f"/api/jobs/{job_id}/cancel")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "cancelled"


def test_time_limit_stops_a_stuck_job(app, client, monkeypatch):
    store = app.extensions["jobs"]
    store.timeout = 1
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed)
    real_popen = __import__("subprocess").Popen
    monkeypatch.setattr("webapp.jobs.subprocess.Popen", lambda command, **kwargs: real_popen(["sh", "-c", "sleep 30"], **kwargs))
    store.run_next()
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "failed" and "limit" in job["error"]


def test_running_out_of_memory_is_explained(app, client, monkeypatch):
    store = app.extensions["jobs"]
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed)
    real_popen = __import__("subprocess").Popen
    monkeypatch.setattr("webapp.jobs.subprocess.Popen", lambda command, **kwargs: real_popen(["sh", "-c", "kill -9 $$"], **kwargs))
    store.run_next()
    assert "out of memory" in client.get(f"/api/jobs/{job_id}").get_json()["error"]


def test_restart_marks_unfinished_jobs(tmp_path, monkeypatch, no_key):
    monkeypatch.setenv("APP_PASSWORD", "x")
    app = create_app(str(tmp_path), start_threads=False)
    client = app.test_client()
    client.post("/login", data={"password": "x"})
    job_id, listed = upload(client, {"s.xlsx": SALES})
    start(client, job_id, listed)
    second = create_app(str(tmp_path), start_threads=False).test_client()
    second.post("/login", data={"password": "x"})
    job = second.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "failed" and "restarted" in job["error"]


def test_old_jobs_and_abandoned_uploads_are_removed(tmp_path):
    store = JobStore(tmp_path, retention_days=7)
    draft = store.create()
    finished = store.create()
    store.update(finished["id"], status="done")
    day = 86400
    assert store.clean(time.time() + 2 * day) == 1
    assert not store.folder(draft["id"]).exists() and store.folder(finished["id"]).exists()
    assert store.clean(time.time() + 8 * day) == 1
    assert not store.folder(finished["id"]).exists()


def test_status_and_qwen_test(client, qwen):
    status = client.get("/api/status").get_json()
    assert status["qwen_ready"] and status["model"] == "qwen-test" and status["max_upload_mb"] == 2048
    qwen.replies = [{"ok": True}]
    assert client.post("/api/qwen-test").get_json()["ok"] is True
    qwen.replies = [(401, "bad key")]
    result = client.post("/api/qwen-test").get_json()
    assert result["ok"] is False and "rejected the API key" in result["error"] and "sk-test" not in result["error"]


def test_sample_job_without_a_key(app, client):
    job = client.post("/api/sample", json={"template": True}).get_json()
    assert job["status"] == "queued" and job["instruction"] == "" and job["template"]
    run_all(app)
    job = client.get(f"/api/jobs/{job['id']}").get_json()
    assert job["status"] == "done"
    assert job["report"]["output"].startswith("Outlet_Report_Template_")
