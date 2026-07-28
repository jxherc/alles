"""Current-host native install/probe/uninstall gate for Phase 9A.

This builds the real private environment and boots the staged app, but uses an
owned temporary home and records service-manager commands instead of changing
the current user's real launchd or systemd state.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cli  # noqa: E402 - standalone gate adds the repository root explicitly
from services import native_install, service_manager  # noqa: E402

DATA = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
HOME = Path(os.environ.get("ALLES_TEST_HOME", "")).expanduser().resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "")


def _verify_owned_root() -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or not RUN_ID:
        raise RuntimeError("set the native-gate ownership proof")
    if DATA == temp_root or temp_root not in DATA.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if HOME == temp_root or temp_root not in HOME.parents:
        raise RuntimeError("ALLES_TEST_HOME must be a system-temporary child")
    if (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("the native-gate data sentinel does not match")
    if (HOME / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("the native-gate home sentinel does not match")


def run() -> None:
    _verify_owned_root()
    layout = native_install.platform_layout(home=HOME)
    assert layout.data_root == DATA
    os.environ["PIP_CACHE_DIR"] = str(DATA / "pip-cache")
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    with mock.patch.object(service_manager, "_home_dir", return_value=HOME):
        result = native_install.install(
            ROOT,
            layout,
            release_id="current-host-gate",
            release_probe=cli._native_install_probe,
            install_source={"kind": "unavailable"},
            runner=runner,
        )
        assert result["release_id"] == "current-host-gate"
        assert native_install.verify_install(layout)["manager"] == layout.manager
        doctor = subprocess.run(
            [str(layout.dispatcher), "doctor"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert doctor.returncode == 0, doctor.stdout + doctor.stderr
        personal = DATA / "owner-data-kept.txt"
        personal.write_text("keep", "utf-8")
        removed = native_install.uninstall_keep_data(layout, runner=runner)

    assert removed["data_kept"] is True
    assert personal.read_text("utf-8") == "keep"
    assert not layout.runtime_root.exists()
    assert not layout.launcher.exists()
    assert not layout.service_definition.exists()
    assert any(command[0] in {"launchctl", "systemctl"} for command in commands)
    print(f"Phase 9 native current-host gate passed with {layout.manager}; owner data kept")


if __name__ == "__main__":
    run()
