"""Establish throwaway Alles data before any test module can import application code."""

import atexit
import os
import tempfile
import uuid
from pathlib import Path


def _proved_temporary_root() -> Path | None:
    if os.environ.get("ALLES_TEST_DATA") != "1":
        return None
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "")
    raw = os.environ.get("ALLES_DATA", "")
    if not run_id or len(run_id) > 128 or not raw:
        return None
    root = Path(raw).expanduser().resolve()
    system_temp = Path(tempfile.gettempdir()).resolve()
    if root == system_temp or system_temp not in root.parents:
        return None
    try:
        if (root / ".alles-test-owner").read_text("utf-8").strip() != run_id:
            return None
    except OSError:
        return None
    return root


_PACKAGE_TEST_DATA = None
_ROOT = _proved_temporary_root()
if _ROOT is None:
    _PACKAGE_TEST_DATA = tempfile.TemporaryDirectory(prefix="alles-tests-bootstrap-")
    atexit.register(_PACKAGE_TEST_DATA.cleanup)
    _ROOT = Path(_PACKAGE_TEST_DATA.name).resolve()
    _RUN_ID = f"unittest-{uuid.uuid4().hex}"
    (_ROOT / ".alles-test-owner").write_text(_RUN_ID, encoding="utf-8")
    os.environ.update(
        {
            "ALLES_DATA": str(_ROOT),
            "ALLES_TEST_DATA": "1",
            "ALLES_TEST_RUN_ID": _RUN_ID,
        }
    )
os.environ.setdefault("AUTH_ENABLED", "false")
