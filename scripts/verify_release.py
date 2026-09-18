"""Validate a clean relocated release, with no dependency on a developer directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    if not (ROOT/'release-build.json').is_file():
        raise ValueError('Run only inside an assembled candidate')
    output = ROOT/'data/logs/diagnostics/release'
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope':'relocated_resource_import_startup_check', 'human_listening':'NOT_VERIFIED'}
    try:
        manifest = json.loads((ROOT/'release-manifest.json').read_text(encoding='utf-8'))
        for row in manifest['files']:
            path = ROOT/row['path']
            if not path.resolve().is_relative_to(ROOT) or path.stat().st_size != row['bytes']:
                raise ValueError('Resource boundary/size mismatch: '+row['path'])
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
                    raise ValueError('Resource hash mismatch: '+row['path'])
        report['manifest_files_verified'] = len(manifest['files'])
        from services.project_paths import project_environment
        from services.engine_service import load_engine_config
        config = load_engine_config()
        system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
        env = project_environment(root=ROOT, python=config.python_path, engine_root=config.engine_root)
        env['PATH'] = os.pathsep.join(str(p) for p in (config.python_path.parent, system/'System32', system))
        env['HF_HUB_OFFLINE'] = '1'
        env['TRANSFORMERS_OFFLINE'] = '1'
        code = """import sys,json,torch,tools.my_utils,text,AR
from pathlib import Path
root=Path(sys.argv[1]).resolve()
paths=[str(Path(p).resolve()) for p in sys.path if p]
assert all(Path(p).is_relative_to(root) for p in paths),paths
assert torch.cuda.is_available()
x=torch.ones((32,32),device='cuda'); assert (x@x).sum().item()==32768
print(json.dumps({'paths':paths,'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0)}))"""
        result = subprocess.run([str(config.python_path), '-s', '-c', code, str(ROOT)], env=env, cwd=config.engine_root,
                                capture_output=True, text=True, encoding='utf-8', timeout=120, check=True)
        report['engine_imports_and_cuda'] = json.loads(result.stdout)
        from setup.EnvironmentSetup.env_setup.checker import run_check
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        diagnostics = run_check(ROOT, ui_port=port)
        failures = [c['key'] for c in diagnostics['checks'] if c['status'] == 'FAIL']
        if failures != ['voice_inputs'] and failures:
            raise ValueError('Environment failures: '+str(failures))
        report['environment'] = {'levels':diagnostics['levels'], 'expected_clean_package_missing_voices':failures == ['voice_inputs']}
        from unittest.mock import patch
        from app import build_app
        with patch('services.workshop_runtime.ensure_local_service', side_effect=AssertionError('startup started workshop')), \
             patch('services.workshop_client.WorkshopClient._client', side_effect=AssertionError('startup connected workshop')):
            demo = build_app()
        report['ui_build_without_workshop'] = True
        if args.serve:
            from services.project_paths import project_environment
            env = project_environment(root=ROOT, python=sys.executable, engine_root=config.engine_root)
            env['GRADIO_ANALYTICS_ENABLED'] = 'False'
            code = "from app import build_app; build_app().launch(server_name='127.0.0.1',server_port="+str(port)+",inbrowser=False)"
            with (output/'ui.log').open('w', encoding='utf-8') as log:
                child = subprocess.Popen([sys.executable, '-s', '-c', code], cwd=ROOT, env=env, stdout=log, stderr=log,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    deadline = time.monotonic()+90
                    while time.monotonic()<deadline:
                        if child.poll() is not None:
                            raise RuntimeError('UI exited before becoming ready')
                        try:
                            with http.open(f'http://127.0.0.1:{port}/config', timeout=2) as response:
                                value = json.load(response)
                            assert value['components']
                            report['http_ui_started'] = True
                            break
                        except OSError:
                            time.sleep(.5)
                    else:
                        raise TimeoutError('UI did not become ready')
                finally:
                    child.terminate()
                    child.wait(timeout=15)
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
