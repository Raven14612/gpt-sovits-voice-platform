import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

from adapters.inference_runtime import InferenceRuntime
from models.schemas import AppError
from services.process_control import run_owned_command

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows process lifetime contract")
class ProcessLifetimeTests(unittest.TestCase):
    def wait_file(self, path):
        for _ in range(100):
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except ValueError:
                    pass
            time.sleep(.05)
        self.fail("Child listener did not start")

    def assert_port_released(self, port):
        for _ in range(100):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    return
            time.sleep(.05)
        self.fail(f"Child process leaked port {port}")

    def command(self, ready, *, normal=False):
        # A grandchild owns the port: checking only the direct child is insufficient.
        listener = ("import socket,time,json,os; from pathlib import Path; "
                    "s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); "
                    f"Path({str(ready)!r}).write_text(json.dumps({{'port':s.getsockname()[1],'pid':os.getpid()}})); "
                    "time.sleep(60)")
        child = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{listener!r}]); time.sleep(60)"
        owner = ("from services.process_lifetime import install_process_lifetime_job; "
                 "install_process_lifetime_job(); "
                 "import subprocess,sys,time; from pathlib import Path; "
                 f"subprocess.Popen([sys.executable,'-c',{child!r}],close_fds=False); "
                 f"ready=Path({str(ready)!r})\n"
                 "while not ready.exists(): time.sleep(.02)\n" +
                 ("" if normal else "time.sleep(60)"))
        return [sys.executable, "-c", owner]

    def test_normal_and_forced_owner_exit_release_grandchild_port(self):
        for normal in (True, False):
            with self.subTest(normal=normal), tempfile.TemporaryDirectory() as directory:
                ready = Path(directory) / "ready.json"
                owner = subprocess.Popen(self.command(ready, normal=normal), cwd=ROOT,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    info = self.wait_file(ready)
                    if not normal:
                        owner.kill()  # No Python finally or atexit handlers run.
                    owner.wait(timeout=10)
                    if normal:
                        self.assertEqual(owner.returncode, 0)
                    self.assert_port_released(info["port"])
                finally:
                    if owner.poll() is None:
                        owner.kill()
                    owner.wait(timeout=10)

    def test_stage_timeout_releases_descendants_and_next_stage_can_run(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready.json"
            with self.assertRaises(subprocess.TimeoutExpired):
                run_owned_command(self.command(ready), cwd=ROOT, timeout=2,
                                  capture_output=True, text=True)
            info = self.wait_file(ready)
            self.assert_port_released(info["port"])
            result = run_owned_command([sys.executable, "-c", "print('next stage')"],
                                       timeout=5, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), "next stage")

    def test_foreign_port_is_preserved_and_its_owner_receives_no_model_request(self):
        runtime = InferenceRuntime()
        adapter = Mock()
        adapter.config.engine_root = ROOT
        adapter.config.python_path = Path(sys.executable)
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(AppError) as caught:
                runtime.ensure(adapter, [], ("g", "s"), port, time.monotonic() + 2, Path(directory))
            self.assertEqual(caught.exception.code, "ENGINE_PORT_BUSY")
            self.assertIsNone(runtime.process)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                self.assertEqual(connection.recv(1024), b"")
            with socket.socket() as probe:
                self.assertEqual(probe.connect_ex(("127.0.0.1", port)), 0)
