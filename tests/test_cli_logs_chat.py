"""alles logs filters, alles ask/chat, backup and dump, and the update facts found on debian 13."""

import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import cli
from services import cli_chat, cli_logs, cli_ui, native_install


def record(level="info", minutes_ago=0, message="hello", logger="alles"):
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    row = {"ts": when.isoformat(), "level": level, "logger": logger, "message": message}
    return json.dumps(row)


class LogFilterTest(unittest.TestCase):
    def test_level_is_a_floor_and_warn_means_warning(self):
        keep = cli_logs.LineFilter(level="warn")
        self.assertFalse(keep(record("info")))
        self.assertTrue(keep(record("warning")))
        self.assertTrue(keep(record("error")))

    def test_since_drops_older_records(self):
        keep = cli_logs.LineFilter(since="30m")
        self.assertFalse(keep(record(minutes_ago=90)))
        self.assertTrue(keep(record(minutes_ago=5)))

    def test_a_traceback_line_goes_with_the_record_above_it(self):
        keep = cli_logs.LineFilter(level="error")
        lines = [record("info"), "  frame of info", record("error"), "  frame of error"]
        self.assertEqual([keep(line) for line in lines], [False, False, True, True])

    def test_uvicorn_lines_have_a_level_too(self):
        keep = cli_logs.LineFilter(level="warning")
        self.assertFalse(keep("INFO:     Application startup complete."))
        self.assertTrue(keep("ERROR:    Exception in ASGI application"))

    def test_grep_matches_any_case(self):
        keep = cli_logs.LineFilter(grep="Ready")
        self.assertTrue(keep(record(message="alles ready")))
        self.assertFalse(keep(record(message="something else")))

    def test_bad_values_say_what_to_type(self):
        with self.assertRaisesRegex(cli_logs.FilterError, "30m, 1h or 2d"):
            cli_logs.LineFilter(since="soon")
        with self.assertRaisesRegex(cli_logs.FilterError, "warning or error"):
            cli_logs.LineFilter(level="loud")

    def test_last_lines_counts_only_what_passes(self):
        lines = [record("info", message=str(i)) for i in range(5)] + [record("error", message="x")]
        kept = cli_logs.last_lines(lines, 2, cli_logs.LineFilter())
        self.assertEqual([json.loads(line)["message"] for line in kept], ["4", "x"])

    def test_render_shows_time_level_logger_and_the_error(self):
        ui = cli_ui.Style(io.StringIO())
        row = json.loads(record("error", message="boom"))
        row["exception"] = {"type": "ValueError", "message": "bad"}
        text = cli_logs.render(json.dumps(row), ui)
        self.assertRegex(text, r"^\d\d:\d\d:\d\d  error  alles  boom  ValueError: bad$")
        self.assertEqual(cli_logs.render("plain text", ui), "plain text")


class LogsCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-cli-logs-")
        self.log = Path(self.tmp.name) / "alles-server.log"
        lines = [record("info", message="one"), record("warning", message="two"), "  traceback"]
        self.log.write_text("\n".join(lines) + "\n")
        self.boot = Path(self.tmp.name) / "boot-check-1.log"

    def tearDown(self):
        self.tmp.cleanup()

    def run_logs(self, *args, boot=False):
        files = [("service", self.log)] + ([("boot-check-1", self.boot)] if boot else [])
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(cli, "_log_files", return_value=files),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            ok = cli.cmd_logs(list(args))
        return ok, out.getvalue(), err.getvalue()

    def test_piped_logs_keep_the_raw_json_lines(self):
        ok, out, _ = self.run_logs("--level", "warn")
        self.assertTrue(ok)
        self.assertEqual(json.loads(out.splitlines()[0])["message"], "two")
        self.assertEqual(out.splitlines()[1], "  traceback")
        self.assertNotIn("\033[", out)

    def test_options_take_both_spellings(self):
        self.assertEqual(cli._logs_options(["-n", "5", "--since=1h"])["count"], 5)
        self.assertEqual(cli._logs_options(["7", "--grep", "x"])["grep"], "x")
        with redirect_stderr(io.StringIO()):
            self.assertIsNone(cli._logs_options(["--level"]))
            self.assertIsNone(cli._logs_options(["--loud"]))
            self.assertIsNone(cli._logs_options(["-n", "many"]))

    def test_boot_reads_the_newest_startup_check_log(self):
        self.boot.write_text("RuntimeError: forced\n")
        ok, out, _ = self.run_logs("boot", boot=True)
        self.assertTrue(ok)
        self.assertIn("RuntimeError: forced", out)
        ok, out, _ = self.run_logs("boot")
        self.assertIn("no boot check logs", out)

    def test_an_unknown_log_name_fails(self):
        ok, _, err = self.run_logs("nonsense")
        self.assertFalse(ok)
        self.assertIn("alles logs list", err)


class Fake(BaseHTTPRequestHandler):
    """The few routes `alles ask` uses, with a password when `locked`."""

    protocol_version = "HTTP/1.1"
    locked = False
    sessions: list = []
    deleted: list = []
    reply_error = None

    def log_message(self, *_):
        pass

    def _json(self, status, body, headers=()):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")

    def do_DELETE(self):
        Fake.deleted.append(self.path)
        self._json(200, {"ok": True})

    def do_POST(self):
        body = self._body()
        if self.path == "/api/auth/login":
            if body.get("password") != "right":
                return self._json(401, {"detail": "invalid password"})
            return self._json(200, {"ok": True}, [("Set-Cookie", "aide_session=tok; HttpOnly")])
        if self.locked and "aide_session=tok" not in (self.headers.get("cookie") or ""):
            return self._json(401, {"detail": "not authenticated", "code": "not_authenticated"})
        if self.path == "/api/sessions":
            Fake.sessions.append(body)
            return self._json(200, {"id": "s1"})
        if self.path == "/api/chat":
            if Fake.reply_error:
                return self._json(400, {"detail": Fake.reply_error, "code": "no_model"})
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("connection", "close")
            self.end_headers()
            for chunk in ({"tool_start": {"name": "search"}}, {"delta": "hi "}, {"delta": "there"}):
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return None
        return self._json(404, {"detail": "nope"})


class AskTest(unittest.TestCase):
    def setUp(self):
        Fake.locked, Fake.sessions, Fake.deleted, Fake.reply_error = False, [], [], None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def ask(self, password=None):
        out, err = io.StringIO(), io.StringIO()
        client = cli_chat.Client(self.url, (lambda: password) if password is not None else None)
        with (
            mock.patch.object(cli, "_chat_client", return_value=client),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            ok = cli.cmd_ask(["what", "now"])
        return ok, out.getvalue(), err.getvalue()

    def test_the_reply_streams_with_tools_on_their_own_line(self):
        ok, out, _ = self.ask()
        self.assertTrue(ok)
        self.assertEqual(out, "  · search\nhi there\n")
        self.assertEqual(Fake.sessions, [{"name": "what now", "mode": "chat"}])

    def test_a_password_is_asked_once_and_the_question_goes_through(self):
        Fake.locked = True
        ok, out, _ = self.ask(password="right")
        self.assertTrue(ok)
        self.assertIn("hi there", out)

    def test_without_a_keyboard_it_says_to_use_a_terminal(self):
        Fake.locked = True
        ok, _, err = self.ask()
        self.assertFalse(ok)
        self.assertIn("run this in a terminal", err)

    def test_a_refused_question_leaves_no_empty_conversation(self):
        Fake.reply_error = "no model is available"
        ok, _, err = self.ask()
        self.assertFalse(ok)
        self.assertIn("no model is available", err)
        self.assertEqual(Fake.deleted, ["/api/sessions/s1"])


class UpdateFactsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-cli-update-")
        self.layout = native_install.platform_layout("Linux", home=Path(self.tmp.name))
        self.layout.runtime_root.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_release_that_failed_its_checks_is_not_called_ready(self):
        old, new = "a" * 40, "b" * 40
        manifest = {"source": {"kind": "git", "commit": old}}
        native_install.remember_failed(self.layout, old, new)
        with (
            mock.patch.object(native_install, "_load_manifest", return_value=manifest),
            mock.patch.object(native_install, "latest_release_commit", return_value=new),
        ):
            cached = native_install.update_check(self.layout)
            asked_again = native_install.update_check(self.layout, refresh=True)
        for check in (cached, asked_again):
            self.assertFalse(check["waiting"])
            self.assertEqual(check["failed"], new)
        with mock.patch.object(native_install, "_load_manifest", return_value=manifest):
            with mock.patch.object(native_install, "latest_release_commit", return_value="c" * 40):
                newer = native_install.update_check(self.layout, refresh=True)
        self.assertTrue(newer["waiting"])
        self.assertIsNone(newer["failed"])

    def test_status_points_at_the_boot_log_for_a_failed_release(self):
        native = mock.Mock(data_root=Path(self.tmp.name) / "data")
        native.previous_release.is_file.return_value = False
        check = {"waiting": False, "failed": "b" * 40}
        with mock.patch.object(native_install, "update_check", return_value=check):
            lines = cli._native_update_lines(native)
        self.assertEqual(
            lines, [(None, "new release", "bbbbbbb failed its checks: alles logs boot")]
        )

    def test_python_cache_from_running_the_installer_keeps_the_source_clean(self):
        status = "?? core/__pycache__/\n?? services/__pycache__/"
        responses = ["a" * 40, "origin/main", status, "/srv/alles.git"]
        with mock.patch.object(native_install, "_git_text", side_effect=responses):
            result = native_install.source_metadata(Path(self.tmp.name))
        self.assertEqual(result["kind"], "git")
        responses = ["a" * 40, "origin/main", "?? notes.txt", "/srv/alles.git"]
        with mock.patch.object(native_install, "_git_text", side_effect=responses):
            self.assertEqual(
                native_install.source_metadata(Path(self.tmp.name))["kind"], "unavailable"
            )
        responses = ["a" * 40, "origin/main", " M app.py", "/srv/alles.git"]
        with mock.patch.object(native_install, "_git_text", side_effect=responses):
            self.assertEqual(
                native_install.source_metadata(Path(self.tmp.name))["kind"], "unavailable"
            )


class DumpTest(unittest.TestCase):
    def test_dump_is_plain_and_frames_itself(self):
        rows = [("release", "abc1234 (source checkout)"), ("password", "on")]
        out = io.StringIO()
        with mock.patch.object(cli, "_dump_lines", return_value=rows), redirect_stdout(out):
            self.assertTrue(cli.cmd_dump([]))
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "--- alles dump ---")
        self.assertEqual(lines[-1], "--- end dump ---")
        self.assertNotIn("\033[", out.getvalue())

    def test_dump_reads_no_secret_columns(self):
        import inspect

        source = inspect.getsource(cli._dump_lines)
        for secret in ("api_key", "auth_password_hash", "oauth_"):
            self.assertNotIn(secret, source)


if __name__ == "__main__":
    unittest.main()
