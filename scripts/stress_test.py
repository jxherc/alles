"""
stress / evidence run — drives the REAL app through every major area and writes
evidence (request, expected, actual, pass/fail) to ~/alles-test-evidence/<ts>/.

does NOT touch your real data: runs against a throwaway in-memory db with auth
off, exactly like the test harness. nothing is deleted; every run is its own
timestamped folder so you can diff over time.

run:  python scripts/stress_test.py
"""
import os
import sys
import json
import traceback
from pathlib import Path
from datetime import datetime

os.environ["AUTH_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import core.database as db
from app import app

# isolated db
_eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
db.Base.metadata.create_all(_eng)
db.SessionLocal.configure(bind=_eng)
client = TestClient(app)

OUT = Path.home() / "alles-test-evidence" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
_results = []   # (area, name, ok, detail)


def _rec(area, name, ok, detail=""):
    _results.append((area, name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {area} :: {name}" + (f"  — {detail}" if detail and not ok else ""))


def check(area, name, fn):
    """run fn(); it returns (ok, detail) or raises. logs evidence either way."""
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"EXC {e}\n{traceback.format_exc()}"
    _rec(area, name, ok, detail)
    return ok


def area_write(area, lines):
    d = OUT / area.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.md").write_text("\n".join(lines), "utf-8")


# ── scenarios ─────────────────────────────────────────────────────────────────
def run_sessions():
    log = [f"# sessions — {datetime.now().isoformat()}", ""]
    sid = {}

    def create():
        r = client.post("/api/sessions", json={"name": "evidence chat"})
        log.append(f"POST /api/sessions -> {r.status_code} {json.dumps(r.json())[:200]}")
        sid["id"] = r.json().get("id")
        return r.status_code == 200 and bool(sid["id"]), ""
    def listed():
        r = client.get("/api/sessions").json()
        log.append(f"GET /api/sessions -> today={len(r.get('today', []))}")
        return any(s["id"] == sid["id"] for s in r["today"]), ""
    def rename():
        r = client.patch(f"/api/sessions/{sid['id']}", json={"name": "renamed"})
        log.append(f"PATCH name -> {r.json().get('name')}")
        return r.json().get("name") == "renamed", ""
    def delete():
        r = client.delete(f"/api/sessions/{sid['id']}")
        log.append(f"DELETE -> {r.json()}")
        return r.json().get("ok") is True, ""
    check("sessions", "create", create)
    check("sessions", "list shows it", listed)
    check("sessions", "rename", rename)
    check("sessions", "delete", delete)
    area_write("sessions", log)


def run_crud(area, base, make, mk_payload, patch_payload=None, name_field="name", upd_method="PATCH"):
    """generic crud evidence for a simple resource."""
    log = [f"# {area} — {datetime.now().isoformat()}", ""]
    holder = {}

    def create():
        r = client.post(base, json=mk_payload)
        log.append(f"POST {base} {json.dumps(mk_payload)[:120]} -> {r.status_code} {json.dumps(r.json())[:200]}")
        holder["id"] = (r.json() or {}).get("id") or (r.json() or {}).get("slug")
        return r.status_code == 200, ""
    def listed():
        r = client.get(base)
        n = len(r.json()) if isinstance(r.json(), list) else len(r.json().get("messages", r.json()))
        log.append(f"GET {base} -> {r.status_code}, {n} item(s)")
        return r.status_code == 200, ""
    check(area, "create", create)
    check(area, "list", listed)
    if patch_payload and holder.get("id"):
        def patch():
            r = client.request(upd_method, f"{base}/{holder['id']}", json=patch_payload)
            log.append(f"{upd_method} {base}/{holder['id']} -> {r.status_code} {json.dumps(r.json())[:160]}")
            return r.status_code == 200, ""
        check(area, "update", patch)
    if holder.get("id"):
        def delete():
            r = client.delete(f"{base}/{holder['id']}")
            log.append(f"DELETE {base}/{holder['id']} -> {r.status_code} {json.dumps(r.json())[:120]}")
            return r.status_code == 200, ""
        check(area, "delete", delete)
    area_write(area, log)


def run_calendar_nl():
    log = [f"# calendar NL quick-add — {datetime.now().isoformat()}", ""]
    def quick():
        r = client.post("/api/calendar/quick", json={"text": "lunch with sam tomorrow 1pm"})
        log.append(f"POST /api/calendar/quick 'lunch with sam tomorrow 1pm' -> {r.status_code}")
        log.append(json.dumps(r.json(), indent=2)[:400])
        j = r.json()
        return r.status_code == 200 and "title" in j and bool(j.get("start_dt")), ""
    check("calendar", "NL quick-add parses", quick)
    area_write("calendar_nl", log)


def run_tasks_nl():
    log = [f"# tasks NL quick-add — {datetime.now().isoformat()}", ""]
    def quick():
        r = client.post("/api/tasks/quick", json={"text": "pay rent every 1st !"})
        log.append(f"POST /api/tasks/quick 'pay rent every 1st !' -> {r.status_code}")
        log.append(json.dumps(r.json(), indent=2)[:400])
        j = r.json()
        return r.status_code == 200 and j.get("repeat") and j.get("priority", 0) >= 1, ""
    check("tasks", "NL quick-add (recurring + priority)", quick)
    area_write("tasks_nl", log)


def run_health_doctor():
    log = [f"# health / doctor — {datetime.now().isoformat()}", ""]
    def deep():
        r = client.get("/health?deep=1").json()
        log.append(json.dumps(r, indent=2))
        return r.get("ok") is True and any(c["label"] == "required dependencies" for c in r["checks"]), ""
    check("health", "deep readiness check", deep)
    area_write("health", log)


def run_setup():
    log = [f"# first-run setup status — {datetime.now().isoformat()}", ""]
    def status():
        r = client.get("/api/setup/status").json()
        log.append(json.dumps(r, indent=2))
        return "configured" in r and "endpoints" in r, ""
    check("setup", "status shape", status)
    area_write("setup", log)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"stress run -> {OUT}\n")
    run_health_doctor()
    run_setup()
    run_sessions()
    run_crud("projects", "/api/projects", None, {"name": "Ev Project"}, {"description": "d"})
    run_crud("personas", "/api/personas", None, {"name": "Ev Persona", "system_prompt": "be terse"}, {"name": "Ev2", "system_prompt": "x"})
    run_crud("contacts", "/api/contacts", None, {"name": "Ev Contact", "email": "e@x.com"}, {"phone": "123"})
    run_crud("notes", "/api/cookbook", None, {"name": "ev cmd", "prompt": "do {args}"}, {"name": "ev cmd", "prompt": "p", "description": "d"})
    run_crud("skills", "/api/skills", None, {"name": "Ev Skill", "description": "test", "when_to_use": "during evidence runs"}, {"name": "Ev Skill", "description": "v2"}, upd_method="PUT")
    run_crud("reminders", "/api/reminders", None, {"text": "ev reminder", "trigger_at": "2099-01-01T09:00:00"})
    run_crud("webhooks", "/api/webhooks", None, {"name": "evh", "url": "https://example.com"}, {"name": "evh2", "url": "https://example.com", "events": ["message"]})
    run_calendar_nl()
    run_tasks_nl()

    # summary
    total = len(_results)
    passed = sum(1 for *_, ok, _ in [(a, n, ok, d) for a, n, ok, d in _results] if ok)
    failed = total - passed
    summary = [
        f"# alles stress / evidence run",
        f"_{datetime.now().isoformat()}_",
        "",
        f"**{passed}/{total} checks passed** ({failed} failed)",
        "",
        "| area | check | result |",
        "|---|---|---|",
    ]
    for area, name, ok, detail in _results:
        summary.append(f"| {area} | {name} | {'✅ pass' if ok else '❌ FAIL'} |")
    if failed:
        summary += ["", "## failures", ""]
        for area, name, ok, detail in _results:
            if not ok:
                summary.append(f"### {area} :: {name}\n```\n{detail[:1500]}\n```")
    (OUT / "SUMMARY.md").write_text("\n".join(summary), "utf-8")
    print(f"\n{passed}/{total} passed -> {OUT / 'SUMMARY.md'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
