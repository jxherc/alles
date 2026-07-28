import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import anyio
from starlette.websockets import WebSocketDisconnect

from routes import shell as shell_routes
from tests import pw_shell_pty_live
from tests._client import ApiTest


def _receive_bytes_until(terminal, expected, *, timeout: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout
    output = b""
    while expected not in output:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"terminal output did not include {expected!r} before timeout")

        async def receive():
            with anyio.fail_after(remaining):
                return await terminal._send_rx.receive()

        message = terminal.portal.call(receive)
        terminal._raise_on_close(message)
        output += message["bytes"]
    return output


@unittest.skipUnless(os.name == "posix", "PTY terminal is available on macOS and Linux")
class ShellPtyTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory(prefix="alles-pty-")
        self.root = Path(self.folder.name).resolve()

    def tearDown(self):
        self.folder.cleanup()
        super().tearDown()

    def test_session_terminal_is_interactive_and_scoped_to_working_directory(self):
        session = self.client.post(
            "/api/sessions",
            json={"name": "terminal", "working_dir": str(self.root)},
        ).json()

        with self.client.websocket_connect(
            f"/api/shell/pty?session_id={session['id']}",
            headers={"origin": "http://testserver"},
        ) as terminal:
            ready = terminal.receive_json()
            self.assertEqual(ready["type"], "ready")
            self.assertEqual(Path(ready["cwd"]).resolve(), self.root)
            terminal.send_json({"type": "input", "data": "printf '__ALLES_CWD__%s\\n' \"$PWD\"\r"})
            output = _receive_bytes_until(terminal, str(self.root).encode())

        self.assertIn(b"__ALLES_CWD__", output)
        self.assertIn(str(self.root).encode(), output)

    def test_terminal_foreground_process_owns_the_controlling_terminal(self):
        session = self.client.post(
            "/api/sessions",
            json={"name": "controlling terminal", "working_dir": str(self.root)},
        ).json()
        with self.client.websocket_connect(
            f"/api/shell/pty?session_id={session['id']}",
            headers={"origin": "http://testserver"},
        ) as terminal:
            self.assertEqual(terminal.receive_json()["type"], "ready")
            terminal.send_json(
                {
                    "type": "input",
                    "data": (
                        "python3 -c 'import os; "
                        'print("__ALLES_CTTY__" + str(os.tcgetpgrp(0) == os.getpgrp()))'
                        "'\r"
                    ),
                }
            )
            output = _receive_bytes_until(terminal, b"__ALLES_CTTY__True")

        self.assertIn(b"__ALLES_CTTY__True", output)

    def test_terminal_rejects_cross_origin_websocket(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(
                "/api/shell/pty",
                headers={"origin": "https://attacker.example"},
            ):
                pass
        self.assertEqual(caught.exception.code, 1008)

    def test_terminal_origin_scheme_must_match_the_websocket_scheme(self):
        websocket = mock.Mock()
        websocket.headers = {"host": "alles.example"}
        websocket.url.scheme = "wss"
        with mock.patch.object(shell_routes, "trusted_hosts", return_value=("alles.example",)):
            websocket.headers["origin"] = "http://alles.example"
            self.assertFalse(shell_routes._same_origin(websocket))
            websocket.headers["origin"] = "https://alles.example"
            self.assertTrue(shell_routes._same_origin(websocket))
            websocket.url.scheme = "ws"
            self.assertFalse(shell_routes._same_origin(websocket))

    def test_terminal_rejects_a_rebinding_domain_even_when_origin_matches_host(self):
        websocket = mock.Mock()
        websocket.url.scheme = "ws"
        websocket.headers = {
            "origin": "http://attacker.example",
            "host": "attacker.example",
        }
        self.assertFalse(shell_routes._same_origin(websocket))

        websocket.headers = {
            "origin": "http://127.0.0.1:6769",
            "host": "127.0.0.1:6769",
        }
        self.assertTrue(shell_routes._same_origin(websocket))

    def test_client_working_directory_query_cannot_bypass_required_terminal_context(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(
                f"/api/shell/pty?working_dir={self.root}",
                headers={"origin": "http://testserver"},
            ) as terminal:
                terminal.receive_json()
        self.assertEqual(caught.exception.code, 1008)

    def test_live_browser_gate_requires_an_owned_throwaway_data_root(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALLES_TEST_DATA"):
                pw_shell_pty_live._require_throwaway_data_root()

        run_id = "pty-browser-owned-run"
        with tempfile.TemporaryDirectory(prefix="alles-pty-browser-") as folder:
            root = Path(folder).resolve()
            (root / ".alles-test-owner").write_text(run_id, encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "ALLES_TEST_DATA": "1",
                    "ALLES_TEST_RUN_ID": run_id,
                    "ALLES_DATA": str(root),
                },
                clear=True,
            ):
                with mock.patch.object(
                    pw_shell_pty_live, "require_server_ownership"
                ) as require_ownership:
                    self.assertEqual(pw_shell_pty_live._require_throwaway_data_root(), root)

        require_ownership.assert_called_once_with(pw_shell_pty_live.URL, run_id)

    def test_terminal_explicitly_rechecks_authentication_before_accepting(self):
        websocket = mock.Mock()
        websocket.close = mock.AsyncMock()
        websocket.accept = mock.AsyncMock()

        with mock.patch.object(
            shell_routes,
            "require_auth",
            side_effect=shell_routes.HTTPException(401, "not authenticated"),
        ):
            asyncio.run(shell_routes.shell_pty(websocket))

        websocket.close.assert_awaited_once_with(code=1008, reason="not authenticated")
        websocket.accept.assert_not_awaited()

    def test_ready_send_failure_terminates_the_spawned_shell_and_closes_the_pty(self):
        websocket = mock.Mock()
        websocket.headers = {"origin": "http://testserver", "host": "testserver"}
        websocket.url.scheme = "ws"
        websocket.accept = mock.AsyncMock()
        websocket.send_json = mock.AsyncMock(side_effect=WebSocketDisconnect())
        websocket.close = mock.AsyncMock()
        process = mock.Mock(pid=12345)
        session = mock.Mock()
        session.close = mock.Mock()
        add_reader = mock.Mock()
        remove_reader = mock.Mock()

        async def run():
            loop = asyncio.get_running_loop()
            with (
                mock.patch.object(loop, "add_reader", add_reader),
                mock.patch.object(loop, "remove_reader", remove_reader),
            ):
                await shell_routes.shell_pty(websocket)

        with (
            mock.patch.object(shell_routes, "SessionLocal", return_value=session),
            mock.patch.object(shell_routes, "_execution_cwd", return_value=str(self.root)),
            mock.patch.object(shell_routes, "_interactive_shell", return_value="/bin/sh"),
            mock.patch.object(shell_routes.pty, "openpty", return_value=(101, 102)),
            mock.patch.object(shell_routes, "_resize_pty"),
            mock.patch.object(shell_routes.subprocess, "Popen", return_value=process) as spawn,
            mock.patch.object(shell_routes.os, "close") as close,
            mock.patch.object(shell_routes.os, "set_blocking"),
            mock.patch.object(shell_routes, "_terminate_pty_process") as terminate,
            self.assertRaises(WebSocketDisconnect),
        ):
            asyncio.run(run())

        websocket.accept.assert_awaited_once()
        terminate.assert_called_once_with(process)
        self.assertEqual(
            spawn.call_args.args[0],
            [
                shell_routes.sys.executable,
                "-c",
                shell_routes._PTY_CHILD_BOOTSTRAP,
                "/bin/sh",
            ],
        )
        self.assertNotIn("preexec_fn", spawn.call_args.kwargs)
        self.assertIn("TIOCSCTTY", shell_routes._PTY_CHILD_BOOTSTRAP)
        self.assertIn(mock.call(102), close.call_args_list)
        self.assertIn(mock.call(101), close.call_args_list)
        remove_reader.assert_called_once_with(101)

    def test_pty_input_retries_blocked_and_short_writes_without_data_loss(self):
        delivered = bytearray()
        outcomes = iter((2, BlockingIOError(), 3))
        waits = []

        def write(_fd, pending):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            delivered.extend(bytes(pending[:outcome]))
            return outcome

        async def wait(fd):
            waits.append(fd)

        asyncio.run(
            shell_routes._write_pty_input(
                17,
                b"abcde",
                write_fn=write,
                wait_writable=wait,
            )
        )
        self.assertEqual(delivered, b"abcde")
        self.assertEqual(waits, [17])

    def test_pty_input_backpressure_is_bounded_for_disconnect_cleanup(self):
        async def blocked(_fd):
            await asyncio.Event().wait()

        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(
                shell_routes._write_pty_input(
                    17,
                    b"blocked",
                    write_fn=lambda _fd, _pending: (_ for _ in ()).throw(BlockingIOError()),
                    wait_writable=blocked,
                    write_timeout=0.01,
                )
            )
