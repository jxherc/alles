"""
macOS-native integration seams for the Mac mini. none of this runs on the
Windows test box — every entry point guards on darwin and fails loud rather than
pretending. on the Mac these are the wiring points for Keychain + EventKit.

  - keychain_*   : back vault secrets onto the system Keychain via the `security` CLI
  - export_calendar / export_reminders : pull from the Calendar/Reminders apps (EventKit)
"""

import os
import shutil
import subprocess
import sys


def is_mac() -> bool:
    return sys.platform == "darwin"


def _require_darwin():
    if not is_mac():
        raise NotImplementedError("macOS only — this runs on the Mac mini, not the test box")


def icloud_drive_dir() -> str | None:
    """the iCloud Drive folder on macOS (watch-folder ingestion target), else None (11a)."""
    if not is_mac():
        return None
    p = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
    return p if os.path.isdir(p) else p  # return the canonical path even if not yet present


def capabilities() -> dict:
    """what native integration is reachable here — drives the settings status card (11a).
    off-darwin everything is unavailable (the feature fails loud, honestly)."""
    mac = is_mac()
    return {
        "platform": sys.platform,
        "available": mac,
        "keychain": mac and shutil.which("security") is not None,
        "eventkit": mac and shutil.which("icalBuddy") is not None,
        "photokit": mac and shutil.which("osxphotos") is not None,
        "icloud": bool(mac and icloud_drive_dir()),
    }


def _parse_ical_output(text: str) -> list[dict]:
    """turn icalBuddy's bulleted output into structured rows: a `•`/`*` line starts an event
    (its title); indented lines below are that event's detail. cross-platform pure parsing."""
    rows = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s[0] in "•*-" and (len(s) == 1 or s[1] == " "):
            rows.append({"title": s[1:].strip(), "detail": ""})
        elif rows:
            rows[-1]["detail"] = (rows[-1]["detail"] + " " + s).strip()
    return rows


# ── Keychain (uses the built-in `security` CLI, no extra deps) ─────────────────
def keychain_set(service: str, account: str, secret: str):
    _require_darwin()
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret],
        check=True,
    )
    return {"ok": True}


def keychain_get(service: str, account: str):
    _require_darwin()
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def keychain_delete(service: str, account: str):
    _require_darwin()
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account], check=True
    )
    return {"ok": True}


# ── EventKit (Calendar + Reminders) ───────────────────────────────────────────
def export_calendar() -> list[dict]:
    """read events from the macOS Calendar app. wire via `icalBuddy` (brew) or
    pyobjc EventKit on the Mac; this is the seam that the calendar sync calls."""
    _require_darwin()
    if not shutil.which("icalBuddy"):
        raise RuntimeError("install icalBuddy (`brew install ical-buddy`) or wire pyobjc EventKit")
    r = subprocess.run(
        ["icalBuddy", "-b", "* ", "-nc", "eventsToday+7"],
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_ical_output(r.stdout)


def export_reminders() -> list[dict]:
    _require_darwin()
    if not shutil.which("icalBuddy"):
        raise RuntimeError("install icalBuddy (`brew install ical-buddy`) or wire pyobjc EventKit")
    r = subprocess.run(
        ["icalBuddy", "-b", "* ", "-nc", "uncompletedTasks"],
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_ical_output(r.stdout)
