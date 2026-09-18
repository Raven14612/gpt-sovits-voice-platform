"""Real HTTP + browser checks with constructed packages and isolated data.

Only checkpoint sanitization is a test double; no GPU synthesis is claimed.
Requires Node Playwright on NODE_PATH and installed Edge.
"""
from contextlib import ExitStack
from functools import partial
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gradio as gr
from PIL import Image
from app import load_css
from services import voice_service, voice_package_service as packages, task_service
from services.workshop_client import WorkshopClient, load_config
from services.workshop_runtime import stop_local_services
from tests.test_voice_package_service import VoicePackageTests
from ui import workshop_page
from ui.theme import build_theme
from workshop_server.tests.helpers import make_package


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    with TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        config = dict(load_config(root=root), base_url=f'http://127.0.0.1:{free_port()}', auto_start_local=True)
        client = WorkshopClient(root=root, config=config)
        stack.callback(stop_local_services)
        for i in range(9):
            def modify(manifest, files, i=i):
                manifest['voice']['display_name'] = f'测试音色 {i+1:02d}'
                manifest['voice']['description'] = '临时浏览器测试音色，用于检查封面、下载和安装交互。'
            package = make_package(root / f'{i}.rvoice', transform=modify)
            if i == 0:
                other = WorkshopClient(root=root / 'other-publisher', config=dict(config, auto_start_local=False))
                other.upload_voice(package, client._upload_token())
            else:
                client.upload_voice(package)
        cover = root / 'cover.png'
        Image.new('RGB', (800, 500), '#67829e').save(cover)
        index = root / 'data/index/voices.json'
        stack.enter_context(patch.object(workshop_page, 'WorkshopClient', partial(WorkshopClient, root=root, config=config)))
        stack.enter_context(patch.object(workshop_page, 'load_config', lambda: config))
        stack.enter_context(patch.object(workshop_page, 'voice_choices', lambda: [(v.display_name, v.voice_id) for v in voice_service.list_voices(index)]))
        for module in (workshop_page, packages, voice_service):
            stack.enter_context(patch.object(module, 'PROJECT_ROOT', root))
        stack.enter_context(patch.object(voice_service, 'VOICE_INDEX', index))
        stack.enter_context(patch.object(task_service, 'PROJECT_ROOT', root))
        stack.enter_context(patch.object(task_service, '_PROCESS_LOCK_PATH', root / 'data/.gpu-process.lock'))
        stack.enter_context(patch('services.storage_lock.PROJECT_ROOT', root))
        def slow_sanitizer(*args):
            time.sleep(1)  # Make the pre-export feedback observable in the browser.
            return VoicePackageTests.fake_sanitizer(*args)
        stack.enter_context(patch.object(packages, '_sanitize', side_effect=slow_sanitizer))
        with gr.Blocks(css=load_css(), theme=build_theme(), analytics_enabled=False, fill_width=True, elem_classes=["rj-theme"]) as demo:
            with gr.Row(elem_id='topbar'):
                gr.Markdown('# 创意工坊 · 隔离浏览器验证', elem_id='brand-title')
            with gr.Row(elem_id='app-shell'):
                with gr.Column(elem_id='sidebar', scale=0, min_width=220):
                    enter = gr.Button('音色创意工坊', variant='primary')
                with gr.Column(elem_id='page-content'):
                    state = {'selected_voice': gr.State(None)}
                    local, search, outputs = workshop_page.render_workshop_page(state, gr.State(0))
            enter.click(workshop_page.refresh_workshop, search, outputs)
            enter.click(lambda: gr.update(choices=workshop_page.voice_choices()), outputs=local)
            demo.load(None, js=(ROOT / 'assets/workshop-dialog.js').read_text(encoding='utf-8'))
        try:
            port = free_port()
            demo.queue().launch(server_name='127.0.0.1', server_port=port, prevent_thread_lock=True, quiet=True)
            env = dict(os.environ, WORKSHOP_SMOKE_URL=f'http://127.0.0.1:{port}', WORKSHOP_SMOKE_COVER=str(cover))
            result = subprocess.run(['node', str(Path(__file__).with_suffix('.cjs'))], env=env)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            demo.close()


if __name__ == '__main__':
    main()
