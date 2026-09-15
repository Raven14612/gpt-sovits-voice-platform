"""Stdlib-only diagnostics; UI/model imports happen in their own subprocesses."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from services.project_paths import project_environment, resolve_project_path
from services.path_migration import apply_changes, atomic_write, encoded, rollback

PROBE = Path(__file__).with_name('probe.py')
MARKER = 'ENV_SETUP_RESULT='


def _run(cmd, cwd=None, env=None, timeout=45):
    started = time.monotonic()
    try:
        process = subprocess.run(list(map(str, cmd)), cwd=cwd, env=env, timeout=timeout,
                                 capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        return process.returncode, (process.stdout + '\n' + process.stderr).strip(), int((time.monotonic()-started)*1000)
    except subprocess.TimeoutExpired:
        return -2, f'Probe timed out after {timeout} seconds', int((time.monotonic()-started)*1000)
    except OSError as exc:
        return -1, str(exc), int((time.monotonic()-started)*1000)


def _port(port):
    with socket.socket() as listener:
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_config(root):
    path = root / 'config/engine.local.json'
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict):
        raise ValueError('engine.local.json must contain a JSON object')
    return raw


def config_preview(root, engine, python):
    root = Path(root).resolve()
    raw = read_config(root)
    candidate = dict(raw)
    for key, value in [('engine_root', engine), ('python_path', python)]:
        if not value:
            raise ValueError(f'Missing {key}')
        path = resolve_project_path(value, root=root)
        if not path.is_relative_to(root) or not path.exists():
            raise ValueError(f'{key} must exist inside project: {path}')
        candidate[key] = path.relative_to(root).as_posix()
    candidate.setdefault('profile', 'local-gpt-sovits')
    candidate.update(max_gpu_jobs=1, parallel_infer=False)
    return {'before': raw, 'after': candidate, 'changed': raw != candidate}


def apply_config(root, preview):
    root = Path(root).resolve()
    if read_config(root) != preview['before']:
        raise ValueError('Config changed since preview; inspect it again')
    if not preview['changed']:
        return None
    return apply_changes(root, {'config/engine.local.json': encoded(preview['after'])})


@contextmanager
def gpu_probe_lock(root):
    """Coordinate with the existing model-job file lock, without importing services."""
    if os.name != 'nt':
        raise OSError('GPU diagnostics require Windows')
    import msvcrt
    path = Path(root) / 'data/.gpu-process.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def readiness(checks, groups):
    statuses = [item['status'] for item in checks if set(item['groups']) & set(groups)]
    if not statuses or 'NOT_VERIFIED' in statuses:
        result = 'NOT_VERIFIED'
    else:
        result = 'READY'
    return 'NOT_READY' if any(s in {'FAIL', 'WARN'} for s in statuses) else result


def sanitized_report(result):
    """Allowlist public fields; never copy arbitrary subprocess output or config extras."""
    public = {key: result[key] for key in ['schema_version', 'scope', 'summary', 'readiness',
              'levels', 'training_executed', 'synthesis_executed', 'checked_at']}
    public['checks'] = [{key: row[key] for key in ['key', 'title', 'status', 'groups', 'duration_ms',
                        'checked_at', 'next_action']} for row in result['checks']]
    public['config_write'] = {'status': result.get('config_write', {}).get('status', 'not_requested')}
    return public


def save_report(result, path):
    atomic_write(path, encoded(result))
    public_path = Path(path).with_name(Path(path).stem + '-sanitized.json')
    atomic_write(public_path, encoded(sanitized_report(result)))
    return public_path


def run_check(project_root, engine_root=None, engine_python=None, *, ui_python=None,
              write_config=False, report_path=None, include_gpu=True, port=9888,
              ui_port=7860, timeout=60, verify_hashes=True, probe_dependencies=True):
    root = Path(project_root).resolve()
    checks = []
    result = {'schema_version': 3, 'scope': 'environment_diagnostics', 'checks': checks,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'project_root': str(root),
              'training_executed': False, 'synthesis_executed': False}

    def add(key, status, message='', *, groups=('base',), actual=None, ms=0, command=None,
            action='See setup/EnvironmentSetup/PREPARE.md', expected='PASS'):
        checks.append({'key': key, 'title': key, 'status': status, 'message': str(message),
                       'actual': actual, 'expected': expected, 'next_action': action if status != 'PASS' else '',
                       'groups': list(groups), 'duration_ms': ms,
                       'checked_at': datetime.now(timezone.utc).isoformat(), 'command': command})

    add('os', 'PASS' if os.name == 'nt' else 'FAIL', platform.platform())
    add('project', 'PASS' if (root/'app.py').is_file() else 'FAIL', root)
    try:
        raw = read_config(root)
        add('config', 'PASS' if raw else 'NOT_VERIFIED', 'Configuration parsed' if raw else 'No local config yet')
    except (ValueError, OSError) as exc:
        raw = {}
        add('config', 'FAIL', str(exc))
    engine = resolve_project_path(engine_root or raw.get('engine_root') or 'engines/verified-v2pro', root=root)
    python = resolve_project_path(engine_python or raw.get('python_path') or 'engines/verified-v2pro/runtime/python.exe', root=root)
    ui = resolve_project_path(ui_python or 'runtimes/ui/python.exe', root=root)
    result.update(engine_root=str(engine), engine_python=str(python), ui_python=str(ui))
    valid_engine = engine.is_dir() and engine.is_relative_to(root)
    valid_python = python.is_file() and python.is_relative_to(root)
    valid_ui = ui.is_file() and ui.is_relative_to(root)
    add('engine_root', 'PASS' if valid_engine else 'FAIL', engine)
    add('engine_python', 'PASS' if valid_python else 'FAIL', python)
    add('ui_runtime', 'PASS' if valid_ui else 'FAIL', ui, action='Run scripts/assemble_ui_runtime.py with Windows x64 Python 3.13')
    add('separate_interpreters', 'PASS' if ui != python else 'FAIL', 'UI and model interpreters must differ')
    for relative in ['data/outputs', 'data/logs', 'data/cache', 'data/tmp', 'config']:
        try:
            directory = (root/relative).resolve()
            if not directory.is_relative_to(root):
                raise ValueError('Writable directory escapes project')
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as stream:
                stream.write(b'permission probe'); stream.flush(); os.fsync(stream.fileno())
            add('permission_'+relative, 'PASS', directory)
        except (OSError, ValueError) as exc:
            add('permission_'+relative, 'FAIL', str(exc))
    for key, number, groups in [('ui_port', ui_port, ('base',)), ('port', port, ('inference',))]:
        available = _port(number)
        add(key, 'PASS' if available else 'WARN', f'{number}: '+('available' if available else 'occupied'), groups=groups,
            action='Choose --ui-port/--port or close the owning application; no process is terminated')
    try:
        env = project_environment(root=root, python=python, engine_root=engine)
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    except OSError as exc:
        add('environment', 'FAIL', str(exc)); env = None

    def probe(kind, executable, valid, groups):
        if not valid or not valid_engine or not env or not probe_dependencies:
            add(kind+'_imports', 'NOT_VERIFIED', 'Runtime unavailable or dependency probes skipped', groups=groups)
            return None
        cmd = [str(executable), '-s', str(PROBE), kind, '--root', str(root)]
        code, out, ms = _run(cmd, cwd=engine if kind != 'ui' else root, env=env, timeout=timeout)
        data = None
        for line in out.splitlines():
            if line.startswith(MARKER):
                try:
                    data = json.loads(line[len(MARKER):])
                except ValueError:
                    pass
        if code or not data or not data.get('ok'):
            add(kind+'_imports', 'FAIL', out[-3000:], groups=groups, ms=ms, command=cmd,
                actual={'exit_code': code, 'timeout': code == -2})
            return None
        if Path(data['executable']).resolve() != executable:
            add(kind+'_imports', 'FAIL', 'Unexpected interpreter', groups=groups, actual=data, ms=ms)
            return None
        return data, cmd, ms

    ui_data = probe('ui', ui, valid_ui, ('base',))
    if ui_data:
        data, cmd, ms = ui_data
        local = all(Path(item['file']).resolve().is_relative_to(ui.parent) for item in data['modules'].values())
        add('ui_imports', 'PASS' if local else 'FAIL', 'UI dependencies and Gradio build', actual=data, ms=ms, command=cmd)
    model_data = probe('model', python, valid_python, ('inference', 'training'))
    if model_data:
        data, cmd, ms = model_data
        for group, modules in data['groups'].items():
            ok = all(m['ok'] and m['file'] and Path(m['file']).resolve().is_relative_to(root) for m in modules.values())
            add('model_'+group, 'PASS' if ok else 'FAIL', 'Dependency imports', groups=(group,), actual=modules, command=cmd, ms=ms)
    if include_gpu and valid_python and valid_engine and env:
        try:
            with gpu_probe_lock(root):
                cmd = [str(python), '-s', str(PROBE), 'gpu', '--root', str(root)]
                code, out, ms = _run(cmd, cwd=engine, env=env, timeout=timeout)
            payload = next((json.loads(line[len(MARKER):]) for line in out.splitlines() if line.startswith(MARKER)), {})
            ok = code == 0 and payload.get('ok') and payload.get('tensor_sum') == 4096.0
            add('cuda_tensor', 'PASS' if ok else 'FAIL', out[-2500:], groups=('inference', 'training'),
                actual={'exit_code': code, 'timeout': code == -2, **payload}, ms=ms, command=cmd)
            if ok:
                supported = bool(re.search(r'RTX\s*50\d\d', payload.get('gpu_name', ''), re.I))
                add('gpu_scope', 'PASS' if supported else 'FAIL', payload['gpu_name'], groups=('inference', 'training'),
                    action='This MVP supports verified Windows NVIDIA RTX 50 series only')
                free = payload['free_bytes']
                add('gpu_memory', 'PASS' if free >= 4*1024**3 else 'WARN', 'Current free VRAM; not a training guarantee',
                    actual={'free_bytes': free, 'total_bytes': payload['total_bytes'], 'advisory_floor_bytes': 4*1024**3}, groups=('inference', 'training'))
        except (OSError, ValueError) as exc:
            add('cuda_tensor', 'NOT_VERIFIED', f'GPU probe not executed: {exc}', groups=('inference', 'training'))
    else:
        add('cuda_tensor', 'NOT_VERIFIED', 'GPU probe disabled or interpreter unavailable', groups=('inference', 'training'))
    for name in ['ffmpeg', 'ffprobe']:
        binary = python.parent/(name+'.exe')
        if binary.is_file() and binary.resolve().is_relative_to(root):
            code, out, ms = _run([binary, '-version'], cwd=engine, env=env, timeout=15)
            add(name, 'PASS' if code == 0 else 'FAIL', out[:600], groups=('inference', 'training'), ms=ms, actual={'path': str(binary), 'exit_code': code})
        else:
            add(name, 'FAIL', f'Missing package tool: {binary}', groups=('inference', 'training'), action='Restore the verified engine audio tools; see resource manifest')
    try:
        manifest = json.loads((root/'config/environment-resources.json').read_text(encoding='utf-8'))
        if not manifest.get('files'):
            raise ValueError('Resource manifest is empty')
        for item in manifest['files']:
            path = (engine/item['path']).resolve()
            t = time.monotonic()
            exists = path.is_relative_to(engine) and path.is_relative_to(root) and path.is_file()
            ok = exists and path.stat().st_size == item['bytes']
            if ok and verify_hashes:
                ok = sha256(path) == item['sha256']
            status = ('PASS' if verify_hashes else 'NOT_VERIFIED') if ok else 'FAIL'
            add('resource:'+item['path'], status, 'SHA-256 verified' if status == 'PASS' else 'Missing, changed or hash not checked',
                groups=item['groups'], actual={'target': str(path), 'source': item['source'], 'sha256': item['sha256'], 'bytes': item['bytes']},
                ms=int((time.monotonic()-t)*1000), action='Restore this manifest entry from its source; verify Get-FileHash -Algorithm SHA256')
    except (OSError, ValueError, KeyError) as exc:
        add('resources', 'FAIL', str(exc), groups=('inference', 'training'))
    try:
        voices = json.loads((root/'data/index/voices.json').read_text(encoding='utf-8'))
        available = []
        for voice in voices:
            if voice.get('status') != 'verified':
                continue
            weights = [resolve_project_path(voice.get(key, ''), root=root) for key in ['gpt_weight', 'sovits_weight']]
            if not all(p.is_relative_to(root) and p.is_file() and p.stat().st_size > 0 for p in weights):
                continue
            for ref in voice.get('references', []):
                audio = resolve_project_path(ref.get('audio_path', ''), root=root)
                if audio.is_relative_to(root) and audio.is_file() and ref.get('prompt_text', '').strip():
                    with wave.open(str(audio), 'rb') as wav:
                        if wav.getnframes() > 0:
                            available.append(voice['voice_id']); break
        add('voice_inputs', 'PASS' if available else 'FAIL', 'Available weights and reference inputs; loading still requires synthesis',
            actual=available, groups=('inference',), action='Train/register a voice with package weights and a reference WAV/text')
    except (OSError, ValueError, KeyError, wave.Error) as exc:
        add('voice_inputs', 'FAIL', str(exc), groups=('inference',))
    result['levels'] = {'basic': readiness(checks, ('base',)),
                        'inference': readiness(checks, ('base', 'inference')),
                        'training': readiness(checks, ('base', 'training')),
                        'actual_validation': 'NOT_VERIFIED'}
    result['readiness'] = 'NOT_READY' if 'NOT_READY' in result['levels'].values() else 'NOT_VERIFIED'
    result['summary'] = 'FAIL' if any(c['status'] == 'FAIL' for c in checks) else 'WARN' if any(c['status'] == 'WARN' for c in checks) else 'PASS'
    for level, status in result['levels'].items():
        add('readiness_'+level, 'PASS' if status == 'READY' else status, status, groups=())
    try:
        result['config_preview'] = config_preview(root, engine, python)
        if write_config:
            invalid_config_keys = {'config', 'engine_root', 'engine_python', 'ui_runtime',
                                   'separate_interpreters', 'permission_config'}
            if any(c['status'] == 'FAIL' and c['key'] in invalid_config_keys for c in checks):
                raise ValueError('Resolve invalid config/runtime paths before applying configuration')
            transaction = apply_config(root, result['config_preview'])
            result['config_write'] = {'status': 'applied' if transaction else 'unchanged', 'transaction': str(transaction) if transaction else None}
    except (OSError, ValueError) as exc:
        result['config_error'] = str(exc)
        if write_config:
            result['summary'] = 'FAIL'
    if report_path is not False:
        save_report(result, Path(report_path or root/'setup/EnvironmentSetup/reports/environment-report.json'))
    return result


def main():
    parser = argparse.ArgumentParser(description='Windows RTX 50 series environment diagnostics')
    parser.add_argument('--project-root', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--engine-root'); parser.add_argument('--engine-python'); parser.add_argument('--ui-python')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--write-project-config', action='store_true')
    modes.add_argument('--rollback', type=Path)
    parser.add_argument('--report-path', type=Path)
    parser.add_argument('--sanitized-report', type=Path)
    parser.add_argument('--no-gpu', action='store_true')
    parser.add_argument('--skip-hashes', action='store_true')
    parser.add_argument('--port', type=int, default=9888)
    parser.add_argument('--ui-port', type=int, default=7860)
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--interactive', action='store_true', help='Show preparation guidance; does not auto-write config')
    args = parser.parse_args()
    try:
        if args.rollback:
            transaction = rollback(args.project_root.resolve(), args.rollback)
            print(json.dumps({'rollback': 'completed', 'transaction': str(transaction)}, ensure_ascii=False))
            return 0
        report = run_check(args.project_root, args.engine_root, args.engine_python, ui_python=args.ui_python,
            write_config=args.write_project_config, report_path=args.report_path, include_gpu=not args.no_gpu,
            port=args.port, ui_port=args.ui_port, timeout=args.timeout, verify_hashes=not args.skip_hashes)
        if args.sanitized_report:
            atomic_write(args.sanitized_report, encoded(sanitized_report(report)))
        print(json.dumps({'summary': report['summary'], 'levels': report['levels'],
                          'config_preview': report.get('config_preview'), 'config_error': report.get('config_error')}, ensure_ascii=False, indent=2))
        for item in report['checks']:
            if item['status'] != 'PASS':
                print(f"[{item['status']}] {item['key']}: {item['message']} {item['next_action']}")
        print('Detailed report:', args.report_path or args.project_root/'setup/EnvironmentSetup/reports/environment-report.json')
        return 1 if report['summary'] == 'FAIL' else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'Environment check failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
