"""Run S2 path/entry checks inside a relocated local copy; no model training or synthesis."""
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
from adapters.gpt_sovits import GPTSoVITSAdapter
from services.engine_service import load_engine_config
from services import dataset_service, training_preparation_service as preparation
from services.project_paths import project_environment
from services.wav_service import inspect_wav
from scripts.check_workspace_migration import check


def main():
    evidence = ROOT / 'data/s2-verification'
    evidence.mkdir(parents=True, exist_ok=False)
    config = load_engine_config()
    adapter = GPTSoVITSAdapter(config)
    env = adapter.audio_environment()
    # Exclude developer PATH/import environment from every verification child.
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join([str(config.python_path.parent), str(config.engine_root), str(system/'System32'), str(system)])
    report = {'root': str(ROOT), 'ui_python': sys.executable, 'training_executed': False,
              'synthesis_executed': False, 'checks': []}

    def run(name, command, cwd, environment=env, timeout=120):
        started = time.time()
        result = subprocess.run(command, cwd=cwd, env=environment, timeout=timeout,
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        (evidence/(name+'.stdout.txt')).write_text(result.stdout, encoding='utf-8')
        (evidence/(name+'.stderr.txt')).write_text(result.stderr, encoding='utf-8')
        report['checks'].append({'name': name, 'command': command, 'cwd': str(cwd),
            'started': started, 'finished': time.time(), 'exit_code': result.returncode})
        if result.returncode:
            raise RuntimeError(name + ': ' + result.stderr[-2000:])
        return result.stdout

    try:
        data = check()
        (evidence/'existing-data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        assert data['passed'], data
        code = """import sys,os,json,importlib.util,tempfile,torch
from pathlib import Path
import tools.my_utils, text, AR
root=Path(sys.argv[1]).resolve()
paths=[str(Path(p).resolve()) for p in sys.path if p]
origins={m.__name__:m.__file__ for m in [torch,tools.my_utils,text,AR]}
assert all(Path(p).is_relative_to(root) for p in paths), paths
assert all(Path(p).resolve().is_relative_to(root) for p in origins.values()), origins
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'sys_path':paths,'modules':origins,
'torch':torch.__version__,'cuda':torch.version.cuda,'temp':tempfile.gettempdir()},ensure_ascii=False))
"""
        runtime = json.loads(run('engine-imports', [str(config.python_path), '-s', '-c', code, str(ROOT)], config.engine_root))
        assert Path(runtime['temp']).resolve().is_relative_to(ROOT)
        report['engine_runtime'] = runtime
        run('ui-imports', [sys.executable, '-s', '-c',
            'import sys,gradio,pydantic,yaml,json; print(json.dumps({"executable":sys.executable,"sys_path":sys.path,"gradio":gradio.__file__,"version":gradio.__version__}))'], system)
        datasets = dataset_service.list_datasets(strict=True)
        for record in datasets:
            before = hashlib.sha256(record.feature_manifest.read_bytes()).hexdigest()
            plan = preparation.prepare_training(record.dataset_id, 's2-path-'+record.dataset_id[:12])
            configs = preparation.materialize_training_configs(plan.parent)
            assert hashlib.sha256(record.feature_manifest.read_bytes()).hexdigest() == before
            report.setdefault('training_preparation', []).append({'dataset_id': record.dataset_id,
                'plan': str(plan), 'runtime_configs': [str(p) for p in configs], 'manifest_unchanged': True,
                'training_started': False})
        slices = evidence/'slices'
        slices.mkdir()
        run('real-slice', adapter.slice_command(datasets[0].source_path, slices), config.engine_root, timeout=180)
        wavs = list(slices.glob('*.wav'))
        assert wavs, 'No slice outputs'
        report['slice_outputs'] = [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
            'bytes': p.stat().st_size, 'wav': inspect_wav(p)} for p in wavs]
        # Every remaining model entry is located, without starting GPU jobs.
        report['model_entries'] = adapter.asr_command(slices, evidence/'asr')[:3]
        report['feature_commands'] = [adapter.feature_command(s) for s in
            ['feature_text', 'feature_hubert', 'feature_sv', 'feature_semantic']]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        ui_env = project_environment(root=ROOT, python=sys.executable, engine_root=config.engine_root)
        ui_env['PATH'] = env['PATH']
        run('start-bat-check', [str(system/'System32/cmd.exe'), '/d', '/c', str(ROOT/'start.bat'),
            '--check', '--port', str(port)], system, ui_env)
        command = [sys.executable, '-s', '-u', str(ROOT/'scripts/launch.py'), '--port', str(port)]
        with (evidence/'ui-server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=system, env=ui_env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                report['ui_process'] = {'pid': process.pid, 'command': command, 'started': time.time()}
                deadline = time.monotonic()+90
                http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('UI exited: ' + str(process.returncode))
                    try:
                        with http.open(f'http://127.0.0.1:{port}/config', timeout=2) as response:
                            ui_config = json.load(response)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('UI startup timeout')
                        time.sleep(.5)
                report['ui_process']['components'] = len(ui_config['components'])
                ps = f'Get-CimInstance Win32_Process -Filter "ProcessId = {process.pid}" | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json'
                report['ui_process']['os_identity'] = json.loads(run('ui-process-identity',
                    [str(system/'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile', '-Command', ps], system))
                busy = subprocess.run([sys.executable, '-s', str(ROOT/'scripts/launch.py'), '--check', '--port', str(port)],
                    cwd=system, env=ui_env, timeout=40, capture_output=True, text=True, encoding='utf-8')
                assert busy.returncode != 0 and 'already in use' in busy.stderr and process.poll() is None
                report['port_conflict'] = {'exit_code': busy.returncode, 'message': busy.stderr, 'owner_alive': True}
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=20)
                report['ui_process']['stopped'] = time.time()
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = str(exc)
        raise
    finally:
        (evidence/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'passed': report.get('passed'), 'report': str(evidence/'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
