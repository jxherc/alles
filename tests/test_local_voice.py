"""Offline worker client checks. No speech engine, microphone or provider is run."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import local_voice as voice

READY = {
    "type": "ready",
    "protocol": 1,
    "format": "pcm_s16le",
    "sample_rate": 24_000,
    "channels": 1,
}


class Input:
    def __init__(self, process):
        self.process = process

    def write(self, data):
        request = json.loads(data)
        self.process.requests.append(request)
        self.process.respond(self.process, request)

    async def drain(self):
        await asyncio.sleep(0)


class Process:
    def __init__(self, respond, ready=READY):
        self.stdout = asyncio.StreamReader(limit=voice.MAX_LINE_BYTES)
        self.stderr = asyncio.StreamReader()
        self.stdin = Input(self)
        self.returncode = None
        self.killed = False
        self.respond = respond
        self.requests = []
        if ready is not None:
            self.emit(ready)

    def emit(self, packet):
        self.stdout.feed_data(json.dumps(packet).encode() + b"\n")

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self):
        return self.returncode


def transcription(process, request, **overrides):
    result = {
        "id": request["id"],
        "type": "result",
        "text": "hello 你好",
        "language": "zh",
        "metrics": {"processing_ms": 3, "input_seconds": 1.0, "vad_speech_seconds": 0.8},
        **overrides,
    }
    process.emit(result)
    process.emit({"id": request["id"], "type": "done"})


def audio(process, request, *, pcm=b"\x01\x00\x02\x00", **overrides):
    process.emit(
        {
            "id": request["id"],
            "type": "audio",
            "seq": 0,
            "pcm_b64": base64.b64encode(pcm).decode(),
            "sample_rate": 24_000,
            "channels": 1,
            **overrides,
        }
    )


def speech(process, request):
    audio(process, request)
    process.emit(
        {
            "id": request["id"],
            "type": "done",
            "metrics": {"first_pcm_ms": 1, "generation_ms": 2, "output_samples": 2},
        }
    )


class LocalVoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = (Path(self.directory.name) / "runtime").resolve()
        self.root.mkdir()
        self.manifest = {
            "schema_version": 1,
            "status": "ready",
            "python": ".venv/bin/python",
            "models": {name: {"path": path} for name, path in voice._MODEL_PATHS.items()},
            "verified_at": "2026-10-13T00:00:00Z",
            "engine_versions": {"fixture": "1"},
            "files": [],
        }
        for path in sorted(voice._MODEL_FILES):
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            content = b"synthetic model fixture, never loaded"
            file.write_bytes(content)
            self.manifest["files"].append(
                {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            )
        executable = self.root / ".venv/bin/python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        self.save_manifest()
        worker_script = Path(self.directory.name) / "worker.py"
        worker_script.write_text("# inert fixture; subprocess creation is mocked\n")
        self.patch = mock.patch.dict(
            os.environ,
            {
                "ALLES_VOICE_RUNTIME": str(self.root),
                "ALLES_DATA": str(Path(self.directory.name) / "data"),
                "OPENAI_API_KEY": "must-not-reach-worker",
                "HF_TOKEN": "must-not-reach-worker",
                "HTTP_PROXY": "must-not-reach-worker",
                "PYTHONPATH": "must-not-reach-worker",
            },
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.worker_patch = mock.patch.object(voice, "_worker", voice._Worker())
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)
        self.script_patch = mock.patch.object(voice, "WORKER_SCRIPT", worker_script)
        self.script_patch.start()
        self.addCleanup(self.script_patch.stop)
        self.processes = []

    async def asyncTearDown(self):
        await voice.shutdown()

    def save_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def spawn(self, respond=transcription, ready=READY):
        async def create(*_args, **_kwargs):
            process = Process(respond, ready)
            self.processes.append(process)
            return process

        return mock.patch.object(voice.asyncio, "create_subprocess_exec", side_effect=create)

    async def speak(self, text="hello", cancel=None):
        return [
            chunk
            async for chunk in voice.synthesize(text, "fixture-tts", cancel or asyncio.Event())
        ]

    async def transcribe(self, cancel=None):
        return await voice.transcribe(
            b"synthetic audio", "audio/webm;codecs=opus", "fixture-stt", cancel or asyncio.Event()
        )

    def test_metadata_is_passive_and_requires_verified_manifest(self):
        before = {path: path.stat().st_mtime_ns for path in self.root.rglob("*")}
        with mock.patch.object(voice.asyncio, "create_subprocess_exec") as spawn:
            self.assertTrue(voice.metadata_status()["available"])
            spawn.assert_not_called()
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in self.root.rglob("*")})
        self.assertFalse((self.root / "jobs").exists())
        self.manifest["status"] = "assets_verified"
        self.save_manifest()
        self.assertFalse(voice.metadata_status()["available"])

    def test_metadata_rejects_missing_changed_and_escaping_assets(self):
        entry = self.manifest["files"][0]
        original = dict(entry)
        for change in ({"size": 1}, {"path": "../outside"}, {"sha256": "invalid"}):
            with self.subTest(change=change):
                entry.update(change)
                self.save_manifest()
                self.assertFalse(voice.metadata_status()["available"])
                entry.clear()
                entry.update(original)
        self.manifest["files"].pop()
        self.save_manifest()
        self.assertFalse(voice.metadata_status()["available"])

    def test_metadata_rejects_arbitrary_python_and_malformed_manifest(self):
        self.manifest["python"] = "/bin/sh"
        self.save_manifest()
        self.assertFalse(voice.metadata_status()["available"])
        (self.root / "manifest.json").write_text("[bad")
        self.assertFalse(voice.metadata_status()["available"])

    async def test_transcription_uses_owned_temporary_audio_and_cleans_it(self):
        observed = []

        def respond(process, request):
            path = Path(request["audio_path"])
            observed.append(path)
            self.assertTrue(path.is_relative_to(self.root / "jobs"))
            self.assertEqual(path.read_bytes(), b"synthetic audio")
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            transcription(process, request)

        with self.spawn(respond) as spawn:
            result = await self.transcribe()
        self.assertEqual(result["text"], "hello 你好")
        self.assertEqual(result["language"], "zh")
        self.assertFalse(observed[0].exists())
        self.assertEqual(list((self.root / "jobs").iterdir()), [])
        self.assertEqual(spawn.call_count, 1)
        self.assertIsNone(voice._worker.owner)

    async def test_persistent_worker_and_fresh_wire_identity_for_each_operation(self):
        with self.spawn(speech) as spawn:
            self.assertEqual(await self.speak(), [b"\x01\x00\x02\x00"])
            self.assertEqual(await self.speak(), [b"\x01\x00\x02\x00"])
        self.assertEqual(spawn.call_count, 1)
        requests = self.processes[0].requests
        self.assertNotEqual(requests[0]["id"], requests[1]["id"])
        self.assertFalse(self.processes[0].killed)

    async def test_worker_environment_has_no_inherited_secrets_or_shell(self):
        with self.spawn() as spawn:
            await self.transcribe()
        args, options = spawn.call_args
        self.assertEqual(args[0], str(self.root / ".venv/bin/python"))
        self.assertIn("-I", args)
        self.assertNotIn("shell", options)
        env = options["env"]
        for name in ("OPENAI_API_KEY", "HF_TOKEN", "HTTP_PROXY", "PYTHONPATH"):
            self.assertNotIn(name, env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")

    async def test_busy_rejection_never_releases_or_cancels_existing_job(self):
        started = asyncio.Event()
        cancel = asyncio.Event()
        with self.spawn(lambda *_: started.set()):
            first = asyncio.create_task(self.transcribe(cancel))
            await started.wait()
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await self.speak()
            self.assertEqual(raised.exception.code, "voice_busy")
            self.assertEqual(voice._worker.owner, "fixture-stt")
            self.assertFalse(self.processes[0].killed)
            cancel.set()
            with self.assertRaises(voice.LocalVoiceError):
                await first

    async def test_event_cancel_kills_inference_and_cleans_audio(self):
        started = asyncio.Event()
        cancel = asyncio.Event()
        with self.spawn(lambda *_: started.set()):
            task = asyncio.create_task(self.transcribe(cancel))
            await started.wait()
            cancel.set()
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await task
        self.assertEqual(raised.exception.code, "voice_cancelled")
        self.assertTrue(self.processes[0].killed)
        self.assertEqual(list((self.root / "jobs").iterdir()), [])
        self.assertIsNone(voice._worker.owner)

    async def test_task_cancel_kills_inference_and_cleans_audio(self):
        started = asyncio.Event()
        with self.spawn(lambda *_: started.set()):
            task = asyncio.create_task(self.transcribe())
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(self.processes[0].killed)
        self.assertIsNone(voice._worker.owner)
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    async def test_closing_audio_generator_kills_worker_and_releases_owner(self):
        with self.spawn(audio):
            stream = voice.synthesize("hello", "fixture-tts", asyncio.Event())
            self.assertEqual(await anext(stream), b"\x01\x00\x02\x00")
            await stream.aclose()
        self.assertTrue(self.processes[0].killed)
        self.assertIsNone(voice._worker.owner)

    async def test_timeout_terminates_worker_and_next_job_can_restart(self):
        with self.spawn(lambda *_: None), mock.patch.object(voice, "JOB_TIMEOUT", 0.02):
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await self.transcribe()
        self.assertEqual(raised.exception.code, "voice_timeout")
        self.assertTrue(self.processes[0].killed)
        with self.spawn():
            self.assertEqual((await self.transcribe())["text"], "hello 你好")

    async def test_startup_ready_is_validated_and_bounded(self):
        with self.spawn(ready={**READY, "sample_rate": 44_100}):
            with self.assertRaises(voice.LocalVoiceError):
                await self.transcribe()
        self.assertTrue(self.processes[-1].killed)
        with self.spawn(ready=None), mock.patch.object(voice, "START_TIMEOUT", 0.02):
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await self.transcribe()
        self.assertEqual(raised.exception.code, "voice_timeout")
        self.assertTrue(self.processes[-1].killed)

    async def test_cancel_during_spawn_does_not_leave_process_or_reservation(self):
        started = asyncio.Event()
        closed = asyncio.Event()
        cancel = asyncio.Event()

        async def spawn(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        with mock.patch.object(voice.asyncio, "create_subprocess_exec", side_effect=spawn):
            task = asyncio.create_task(self.transcribe(cancel))
            await started.wait()
            cancel.set()
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await task
        self.assertEqual(raised.exception.code, "voice_cancelled")
        self.assertTrue(closed.is_set())
        self.assertIsNone(voice._worker.process)
        self.assertIsNone(voice._worker.owner)

    async def test_simultaneous_spawn_and_cancel_reaps_owned_process(self):
        cancel = asyncio.Event()

        async def spawn(*_args, **_kwargs):
            process = Process(transcription)
            self.processes.append(process)
            cancel.set()
            return process

        with mock.patch.object(voice.asyncio, "create_subprocess_exec", side_effect=spawn):
            with self.assertRaises(voice.LocalVoiceError):
                await self.transcribe(cancel)
        self.assertTrue(self.processes[0].killed)
        self.assertIsNone(voice._worker.owner)

    async def test_invalid_ids_sequences_pcm_formats_and_caps_fail_closed(self):
        cases = [
            {"id": "another-job"},
            {"seq": 1},
            {"seq": True},
            {"sample_rate": 48_000},
            {"channels": 2},
            {"pcm_b64": "not base64!"},
            {"pcm": b"\x00"},
            {"pcm": b""},
        ]
        for case in cases:
            with self.subTest(case=case), self.spawn(lambda p, r: audio(p, r, **case)):
                with self.assertRaises(voice.LocalVoiceError) as raised:
                    await self.speak()
                self.assertEqual(raised.exception.code, "voice_protocol")
                self.assertTrue(self.processes[-1].killed)
                self.assertIsNone(voice._worker.owner)
        with self.spawn(speech), mock.patch.object(voice, "MAX_OUTPUT_BYTES", 2):
            with self.assertRaises(voice.LocalVoiceError):
                await self.speak()

    async def test_output_done_requires_matching_sample_count(self):
        def respond(process, request):
            audio(process, request)
            process.emit(
                {
                    "id": request["id"],
                    "type": "done",
                    "metrics": {
                        "first_pcm_ms": 0,
                        "generation_ms": 1,
                        "output_samples": 50,
                    },
                }
            )

        with self.spawn(respond):
            with self.assertRaises(voice.LocalVoiceError):
                await self.speak()
        self.assertTrue(self.processes[-1].killed)

    async def test_no_speech_result_accepts_auto_language_without_inventing_text(self):
        with self.spawn(lambda p, r: transcription(p, r, text="", language="auto")):
            self.assertEqual((await self.transcribe())["text"], "")

    async def test_input_duration_and_nonfinite_metrics_are_rejected(self):
        for metrics in (
            {"processing_ms": 1, "input_seconds": 60.1, "vad_speech_seconds": 1},
            {"processing_ms": float("nan"), "input_seconds": 1, "vad_speech_seconds": 1},
            {"processing_ms": 1, "input_seconds": 1, "vad_speech_seconds": 2},
        ):
            with self.spawn(lambda p, r: transcription(p, r, metrics=metrics)):
                with self.assertRaises(voice.LocalVoiceError):
                    await self.transcribe()
            self.assertTrue(self.processes[-1].killed)

    async def test_unexpected_duplicate_result_and_early_eof_are_rejected(self):
        def duplicate(process, request):
            transcription(process, request)
            # Replace queued packets with two result frames and no done.
            data = bytes(process.stdout._buffer).splitlines()[0]
            process.stdout._buffer.clear()
            process.stdout.feed_data(data + b"\n" + data + b"\n")

        for respond in (duplicate, lambda process, _: process.kill()):
            with self.spawn(respond):
                with self.assertRaises(voice.LocalVoiceError):
                    await self.transcribe()

    async def test_stdout_and_stderr_are_bounded(self):
        cases = (
            lambda p, _: p.stdout.feed_data(b"x" * (voice.MAX_LINE_BYTES + 1)),
            lambda p, _: p.stderr.feed_data(b"x" * (voice.MAX_STDERR_BYTES + 1)),
        )
        for respond in cases:
            with self.spawn(respond):
                with self.assertRaises(voice.LocalVoiceError):
                    await self.transcribe()
            self.assertTrue(self.processes[-1].killed)

    async def test_worker_errors_never_leak_raw_diagnostics(self):
        def respond(process, request):
            process.emit(
                {
                    "id": request["id"],
                    "type": "error",
                    "code": "engine_failed",
                    "message": "PRIVATE TEXT /private/path api-key",
                }
            )

        with self.spawn(respond):
            with self.assertRaises(voice.LocalVoiceError) as raised:
                await self.transcribe()
        self.assertNotIn("PRIVATE", str(raised.exception))
        self.assertNotIn("api-key", str(raised.exception))

    async def test_input_rejections_do_not_spawn(self):
        with self.spawn() as spawn:
            for data, content_type in ((b"", "audio/webm"), (b"x", "text/plain")):
                with self.assertRaises(voice.LocalVoiceError):
                    await voice.transcribe(data, content_type, "fixture", asyncio.Event())
            with self.assertRaises(voice.LocalVoiceError):
                await self.speak("x" * 501)
            cancelled = asyncio.Event()
            cancelled.set()
            with self.assertRaises(voice.LocalVoiceError):
                await self.transcribe(cancelled)
            spawn.assert_not_called()

    async def test_shutdown_kills_only_owned_process(self):
        with self.spawn():
            await self.transcribe()
        await voice.shutdown()
        self.assertTrue(self.processes[0].killed)
        self.assertIsNone(voice._worker.process)
        await voice.shutdown()


if __name__ == "__main__":
    unittest.main()
