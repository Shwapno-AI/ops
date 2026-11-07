"""Drives a running copy of the site the way a browser does. Used to test the Docker image."""

import io
import sys
import time

import requests
from openpyxl import Workbook, load_workbook

base, password = sys.argv[1].rstrip("/"), sys.argv[2]
web = requests.Session()


def wait_until_up() -> None:
    for _ in range(60):
        try:
            if web.get(f"{base}/healthz", timeout=3).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise SystemExit("The site did not start")


def finished(job: dict) -> dict:
    for _ in range(200):
        job = web.get(f"{base}/api/jobs/{job['id']}", timeout=30).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(2)
    raise SystemExit("The job did not finish")


wait_until_up()
assert web.get(f"{base}/api/jobs", timeout=30).status_code == 401, "the site must require a password"
assert web.post(f"{base}/login", data={"password": password}, timeout=30, allow_redirects=False).status_code == 302, "sign in failed"
status = web.get(f"{base}/api/status", timeout=30).json()
assert status["storage_kept"], "/data should be a mounted volume in this test"

# Sample files into the template, which also exercises LibreOffice as a normal user.
job = finished(web.post(f"{base}/api/sample", json={"template": True}, timeout=30).json())
assert job["status"] == "done", job
report = job["report"]
assert report["status"] != "fail", report
assert any(c["name"] == "Formula check" and c["detail"] == "No formula errors" for c in report["passed"]), report
excel = web.get(f"{base}/api/jobs/{job['id']}/download/{report['output']}", timeout=60)
assert excel.status_code == 200
sheet = load_workbook(io.BytesIO(excel.content)).active
assert sheet["A1"].value == "Outlet Performance Report"
print("Template job OK:", report["output"])

# A file bigger than one upload piece, with a name in Bangla.
workbook = Workbook()
workbook.active.append(["Outlet Code", "Sales", "Note"])
for i in range(400_000):
    workbook.active.append([f"D{i}", i, "x" * 40])
buffer = io.BytesIO()
workbook.save(buffer)
data = buffer.getvalue()
name = "বিক্রয় বড় ফাইল.xlsx"
job_id = web.post(f"{base}/api/jobs", timeout=30).json()["id"]
offset, size = 0, status["chunk_bytes"]
while offset < len(data):
    response = web.put(f"{base}/api/jobs/{job_id}/chunk", params={"kind": "input", "name": name, "offset": offset}, data=data[offset : offset + size], timeout=120)
    response.raise_for_status()
    offset = response.json()["size"]
print(f"Uploaded {len(data) / 1024**2:.1f} MB in pieces of {size / 1024**2:.0f} MB")
started = web.post(f"{base}/api/jobs/{job_id}/start", json={"files": [{"kind": "input", "name": name, "size": len(data)}]}, timeout=30).json()
job = finished(started)
assert job["status"] == "done", job
assert job["report"]["results"][0]["rows"] == 400_000, job["report"]["results"]
print("Large job OK:", job["report"]["output"])
print("All good")
