"""
macOS-native integration seams for the Mac mini. none of this runs on the
Windows test box — every entry point guards on darwin and fails loud rather than
pretending. on the Mac these are the wiring points for Keychain + EventKit.

  - keychain_*   : back vault secrets onto the system Keychain via the `security` CLI
  - export_calendar / export_reminders : pull from the Calendar/Reminders apps (EventKit)
"""
import sys
import shutil
import subprocess


def is_mac() -> bool:
    return sys.platform == "darwin"


def _require_darwin():
    if not is_mac():
        raise NotImplementedError("macOS only — this runs on the Mac mini, not the test box")


# ── Keychain (uses the built-in `security` CLI, no extra deps) ─────────────────
def keychain_set(service: str, account: str, secret: str):
    _require_darwin()
    subprocess.run(["security", "add-generic-password", "-U",
                    "-s", service, "-a", account, "-w", secret], check=True)
    return {"ok": True}


def keychain_get(service: str, account: str):
    _require_darwin()
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def keychain_delete(service: str, account: str):
    _require_darwin()
    subprocess.run(["security", "delete-generic-password", "-s", service, "-a", account], check=True)
    return {"ok": True}


# ── EventKit (Calendar + Reminders) ───────────────────────────────────────────
def export_calendar() -> list[dict]:
    """read events from the macOS Calendar app. wire via `icalBuddy` (brew) or
    pyobjc EventKit on the Mac; this is the seam that the calendar sync calls."""
    _require_darwin()
    if not shutil.which("icalBuddy"):
        raise RuntimeError("install icalBuddy (`brew install ical-buddy`) or wire pyobjc EventKit")
    r = subprocess.run(["icalBuddy", "-b", "* ", "-nc", "eventsToday+7"],
                       capture_output=True, text=True, check=True)
    return [{"raw": line} for line in r.stdout.splitlines() if line.strip()]


def export_reminders() -> list[dict]:
    _require_darwin()
    if not shutil.which("icalBuddy"):
        raise RuntimeError("install icalBuddy (`brew install ical-buddy`) or wire pyobjc EventKit")
    r = subprocess.run(["icalBuddy", "-b", "* ", "-nc", "uncompletedTasks"],
                       capture_output=True, text=True, check=True)
    return [{"raw": line} for line in r.stdout.splitlines() if line.strip()]
