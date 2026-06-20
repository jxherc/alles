#!/usr/bin/env python3
"""progress gate for the autorun. exit 0 iff every task in progress.json is done."""

import json
import sys
from pathlib import Path

P = Path(__file__).parent / "progress.json"


def main():
    if not P.exists():
        print("progress.json missing")
        return 1
    tasks = json.loads(P.read_text(encoding="utf-8"))
    if not tasks:
        print("no tasks yet")
        return 1
    pending = [t for t in tasks if t.get("status") != "done"]
    if pending:
        t = pending[0]
        print(f"PENDING [{t.get('id')}] {t.get('app')} (phase {t.get('phase')}): {t.get('plan', '')}")
        print(f"{len(pending)} of {len(tasks)} task(s) pending")
        return 1
    print(f"ALL DONE — {len(tasks)} task(s) complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
