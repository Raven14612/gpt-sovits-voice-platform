import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from scripts import launch
from services import ui_instance


class LauncherTests(unittest.TestCase):
    def test_instance_requires_matching_workspace_and_live_app_id(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"app_id": 123}')
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory, HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                port = server.server_port
                self.assertIsNone(ui_instance.running_url(port, root))
                ui_instance.register(123, port, root)
                self.assertEqual(ui_instance.running_url(port, root), f"http://127.0.0.1:{port}")
                ui_instance.register(999, port, root)
                self.assertIsNone(ui_instance.running_url(port, root))
                path = ui_instance.instance_path(root, port)
                saved = json.loads(path.read_text())
                saved.update(app_id=123, root=str(root / "another-project"))
                path.write_text(json.dumps(saved))
                self.assertIsNone(ui_instance.running_url(port, root))
            finally:
                server.shutdown()
                thread.join()

    def test_repeated_launch_opens_existing_page_without_loading_engine(self):
        with patch.object(launch.sys, "argv", ["launch.py"]), \
                patch.object(launch, "running_url", return_value="http://127.0.0.1:7860"), \
                patch.object(launch, "preflight") as preflight, \
                patch.object(launch.webbrowser, "open", return_value=True) as browser, redirect_stdout(io.StringIO()):
            self.assertEqual(launch.main(), 0)
            browser.assert_called_once_with("http://127.0.0.1:7860")
            preflight.assert_not_called()

    def test_unrelated_port_error_is_logged_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launch, "ROOT", Path(directory)), \
                patch.object(launch.sys, "argv", ["launch.py"]), patch.object(launch, "running_url", return_value=None), \
                patch.object(launch, "preflight", side_effect=ValueError("Port 7860 is already in use")), \
                patch.object(launch.webbrowser, "open") as browser, redirect_stderr(io.StringIO()):
            self.assertEqual(launch.main(), 1)
            self.assertIn("Port 7860", (Path(directory) / "data/logs/launcher-error.log").read_text())
            browser.assert_not_called()

    def test_check_mode_never_opens_browser(self):
        with patch.object(launch.sys, "argv", ["launch.py", "--check"]), \
                patch.object(launch, "running_url") as running, \
                patch.object(launch, "preflight", return_value={}), redirect_stdout(io.StringIO()):
            self.assertEqual(launch.main(), 0)
            running.assert_not_called()

    def test_recovery_error_propagates_as_startup_failure(self):
        from app import main
        with patch("services.asset_service.recover_deletions", side_effect=OSError("occupied")):
            with self.assertRaisesRegex(RuntimeError, "仓库恢复未完成"):
                main()

    def test_double_click_error_path_pauses_and_preserves_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "start.bat"
            target.write_bytes((launch.ROOT / "start.bat").read_bytes())
            result = subprocess.run(["cmd", "/d", "/c", str(target)], input=b"\n", capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"Press any key to close", result.stdout)
