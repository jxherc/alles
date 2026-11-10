#!/usr/bin/env python3
"""Prove every setting, server panel and setup step has a home in every settings layout (28.28).

Reads the settings nav and panes in static/index.html, the server sections, the setup steps and
the layouts in static/js/settings/organization.js. Prints the inventory as a markdown table with
`--table`; exits 1 when anything has no home or a home that doesn't exist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ORGANIZATION = ROOT / "static" / "js" / "settings" / "organization.js"
SETUP = ROOT / "static" / "js" / "setupwizard.js"
GROUPS = ROOT / "static" / "js" / "specialist_groups.js"

# what each pane is for and how often the owner opens it (the inventory, 28.28 step 1)
JOBS = {
    "general": (
        "your name, text size, compact mode, which bar buttons show",
        "sometimes",
    ),
    "home": ("which sections home shows and in what order", "sometimes"),
    "themes": ("theme, light or dark, accent", "often"),
    "notifications": (
        "language, region, timezone, clock, week start, currency",
        "once",
    ),
    "models": ("which model answers, provider sign in and keys, model roles", "often"),
    "ai": ("how chat shows replies and how much context aide reads", "sometimes"),
    "memory": ("what aide remembers and your standing instructions", "sometimes"),
    "personas": ("the voices aide can answer in", "sometimes"),
    "voice": ("speech in and out", "sometimes"),
    "recall": ("searching your own records", "rarely"),
    "proactive": ("checks aide runs without being asked", "sometimes"),
    "intelligence": ("patterns and suggestions aide notices", "rarely"),
    "andromeda": ("search sources and custom engines, answers, the andromeda app", "sometimes"),
    "tools": (
        "mail, calendar, github, chat channels, mcp and other connections",
        "once",
    ),
    "developer": ("api keys for scripts and shortcuts", "rarely"),
    "rules": ("automations and where results are delivered", "sometimes"),
    "security": ("owner password, privacy, sessions", "rarely"),
    "backup": ("backups and restore", "rarely"),
    "credits": ("version, licenses, credits", "rarely"),
}
# the server app's panels and the first run setup steps live behind one settings entry each
LINKED = {
    "@server": "server",
}
# tags that never close (html void elements and the svg shapes the shell draws)
VOID = {
    "br",
    "img",
    "input",
    "meta",
    "link",
    "hr",
    "source",
    "path",
    "polyline",
    "circle",
    "line",
    "rect",
}
SETUP_HOMES = {
    "basics": "general",
    "access": "security",
    "files": "backup",
    "ai_search": "models",
    "protection": "security",
}


class Panes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nav = []
        self.links = []
        self.controls = {}
        self._stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if "s-nav-item" in cls:
            if a.get("data-pane"):
                self.nav.append(a["data-pane"])
            elif a.get("data-link"):
                self.links.append("@" + a["data-link"])
        pane = None
        if "s-pane" in cls and (a.get("id") or "").startswith("s-pane-"):
            pane = a["id"].removeprefix("s-pane-")
        if tag not in VOID:
            self._stack.append(pane)
        current = next((p for p in reversed(self._stack) if p), None)
        if current and pane is None:
            interactive = (
                tag in ("input", "textarea", "button")
                or "custom-select" in cls
                or a.get("role") in ("switch", "radio", "combobox")
            )
            if interactive:
                name = a.get("id") or a.get("data-i18n") or a.get("aria-label") or tag
                self.controls.setdefault(current, []).append(name)

    def handle_endtag(self, tag):
        if tag not in VOID and self._stack:
            self._stack.pop()


def organizations():
    text = ORGANIZATION.read_text()
    block = re.search(
        r"/\* organizations:start \*/\s*export const ORGANIZATIONS = (\{.*?\});\s*/\* organizations:end \*/",
        text,
        re.S,
    )
    return json.loads(block.group(1))


def server_sections():
    match = re.search(
        r"server: Object\.freeze\(\{[^}]*?sections: Object\.freeze\(\[([^\]]*)\]",
        GROUPS.read_text(),
        re.S,
    )
    return re.findall(r"'([a-z_-]+)'", match.group(1)) if match else []


def setup_steps():
    match = re.search(r"const STEPS = \[([^\]]*)\]", SETUP.read_text())
    return re.findall(r"'([a-z_]+)'", match.group(1))


def check(table: bool) -> list[str]:
    parser = Panes()
    parser.feed(INDEX.read_text())
    panes = parser.nav + parser.links
    problems = []
    layouts = organizations()
    for name, layout in layouts.items():
        homes = [pane for group in layout for pane in group["panes"]]
        for pane in panes:
            if homes.count(pane) != 1:
                problems.append(f"{name}: {pane} has {homes.count(pane)} homes")
        for pane in homes:
            if pane not in panes:
                problems.append(f"{name}: {pane} is not a settings entry")
    for pane in parser.nav:
        if pane not in JOBS:
            problems.append(f"{pane} has no job in the inventory")
    for step in setup_steps():
        if SETUP_HOMES.get(step) not in parser.nav:
            problems.append(f"setup step {step} has no settings home")
    if not server_sections():
        problems.append("server sections not found")
    if table:

        def home(layout, pane):
            for group in layouts[layout]:
                if pane in group["panes"]:
                    return group["group"].split(".")[-1].removeprefix("org_").replace("_", " ")
            return "none"

        print("| entry | what it's for | how often | controls | by job | by how often | by thing |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for pane in panes:
            job, often = JOBS.get(
                pane,
                ("server panels: " + ", ".join(server_sections()), "rarely")
                if pane == "@server"
                else ("", ""),
            )
            controls = len(parser.controls.get(pane, []))
            print(
                f"| {pane} | {job} | {often} | {controls} | {home('jobs', pane)} | {home('often', pane)} | {home('things', pane)} |"
            )
        print()
        print("| setup step | settings home |")
        print("| --- | --- |")
        for step in setup_steps():
            print(f"| {step} | {SETUP_HOMES.get(step)} |")
        print()
        print("| control | pane |")
        print("| --- | --- |")
        for pane, names in parser.controls.items():
            for name in names:
                print(f"| {name} | {pane} |")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="store_true", help="print the inventory")
    problems = check(parser.parse_args().table)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
