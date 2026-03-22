from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from src.plotter_backend import process_utils


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0
        self.pid = 1234

    def poll(self):
        return None

    def communicate(self, timeout=None):
        return "OUT", "ERR"

    def kill(self) -> None:
        return None


class _FakeThread:
    def __init__(self, target=None, args=(), daemon=False) -> None:
        self._target = target
        self._args = args
        self.daemon = daemon

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args)


class _FakeSubprocess:
    PIPE = object()

    class TimeoutExpired(Exception):
        pass

    def __init__(self) -> None:
        self.popen_calls = []
        self.run_calls = []

    def Popen(self, *args, **kwargs):
        self.popen_calls.append((args, kwargs))
        return _FakeProc()

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        return types.SimpleNamespace(returncode=0, stdout="STDOUT", stderr="STDERR")


class ProcessUtilsModuleTests(unittest.TestCase):
    def test_run_cmd_executes_simple_command(self) -> None:
        rc, out, err = process_utils.run_cmd(
            [sys.executable, "-c", "import sys; print('ok'); print('err', file=sys.stderr)"],
            timeout_s=10.0,
        )
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)
        self.assertIn("err", err)

    def test_run_cmd_uses_popen_for_watched_inkscape_pdf_call(self) -> None:
        fake_subprocess = _FakeSubprocess()
        fake_threading = types.SimpleNamespace(Thread=_FakeThread)

        rc, out, err = process_utils.run_cmd(
            ["inkscape.exe", "sample.pdf", "--export-type=svg"],
            platform="linux",
            subprocess_module=fake_subprocess,
            threading_module=fake_threading,
            inkscape_pdf_dialog_watcher_enabled=True,
        )

        self.assertEqual((rc, out, err), (0, "OUT", "ERR"))
        self.assertEqual(len(fake_subprocess.popen_calls), 1)
        self.assertEqual(len(fake_subprocess.run_calls), 0)

    def test_open_with_default_viewer_logs_formatted_error(self) -> None:
        messages: list[str] = []

        def _failing_startfile(_path: str) -> None:
            raise OSError("boom")

        process_utils.open_with_default_viewer(
            Path("C:/tmp/out.pdf"),
            logger=messages.append,
            startfile=_failing_startfile,
            format_internal_exception=lambda prefix, exc: f"{prefix}: {type(exc).__name__}: {exc}",
        )

        self.assertEqual(messages, ["Cannot open preview automatically: OSError: boom"])
