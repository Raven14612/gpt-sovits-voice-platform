"""Assemble immutable RTX50 source/runtime candidates from an explicit allowlist.

Never copy developer data or private config; never overwrite an existing destination.
The output is a validation candidate, not approval to redistribute dependencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ('adapters', 'assets', 'services', 'ui', 'tests', 'workshop_server', 'scripts', 'setup', 'uml')
FILES = ('.gitignore', 'app.py', 'start.bat', 'README.md', 'LICENSE', 'NOTICE.md', 'requirements.txt', 'AGENTS.md',
         'models/__init__.py', 'models/schemas.py',
         'setup/EnvironmentSetup/README.md', 'setup/EnvironmentSetup/PREPARE.md', 'setup/EnvironmentSetup/start.bat')
CONFIGS = ('engine.example.json', 'engine.portable.example.json', 'emotion-model.example.json', 'workshop.example.json',
           'environment-resources.json', 'ui-requirements.lock', 'ui-runtime.lock.json', 'emotion-export-requirements.txt', 'release.json')
SCRIPTS = ('launch.py', 'assemble_ui_runtime.py', 'assemble_release.py', 'verify_release.py', 'verify_mvp_workflow.py',
           'migrate_project_paths.py', 'migrate_storage.py', 'relocate_engine_runtime.py', 'sanitize_voice_checkpoint.py',
           'prepare_emotion_model.py', 'lock_emotion_dependencies.py', 'verify_emotion_model.py',
           'workshop_browser_smoke.py', 'workshop_browser_smoke.cjs')
ENGINE_FILES = ('api.py', 'api_v2.py', 'config.py', 'LICENSE', 'README.md', 'requirements.txt', 'extra-req.txt')
SKIP_PARTS = {'__pycache__', '.git', '.cache', '.pytest_cache', '.ipynb_checkpoints'}
MODEL_SUFFIXES = {'.ckpt', '.pth', '.safetensors', '.onnx'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def allowed_tree(base):
    for directory, children, names in os.walk(base, followlinks=False):
        if Path(directory).is_symlink() or Path(directory).is_junction() or not Path(directory).resolve().is_relative_to(base.resolve()):
            raise ValueError(f'Linked/outside directory: {directory}')
        children[:] = sorted(n for n in children if n not in SKIP_PARTS)
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix.lower() in ('.pyc', '.pyo', '.tmp'):
                continue
            if path.suffix.lower() == '.log' and name != 'record.log':
                continue
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(base.resolve()):
                raise ValueError(f'Linked/outside file: {path}')
            yield path


def select_files(root, kind):
    paths = [root / p for p in FILES]
    paths += [root / 'config' / p for p in CONFIGS]
    paths += [root / 'scripts' / p for p in SCRIPTS]
    paths += list(allowed_tree(root / 'Documents'))
    for tree in TREES:
        paths.extend(allowed_tree(root / tree))
    # Include every first-party model source file, but add the large emotion
    # model only through its pinned runtime manifest below.
    paths += [path for path in allowed_tree(root / 'models')
              if path.relative_to(root / 'models').parts[0] != 'emotion']
    # Ship the complete vendored source tree. Downloaded/trained weight formats
    # stay out of this tree; the runnable engine resources are selected from
    # the independently verified engine snapshot below.
    for path in allowed_tree(root / 'third_party'):
        if path.suffix.lower() not in MODEL_SUFFIXES:
            paths.append(path)
    if kind == 'runtime':
        engine = root / 'engines/verified-v2pro'
        paths += [engine / p for p in ENGINE_FILES]
        for tree in ('runtime', 'GPT_SoVITS', 'tools'):
            paths.extend(allowed_tree(engine / tree))
        paths.extend(allowed_tree(root / 'runtimes/ui'))
        emotion = root / 'models/emotion/emotion-zh-v1'
        manifest_path = emotion / 'model-manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        paths.append(manifest_path)
        for name, info in manifest['files'].items():
            path = emotion / name
            if not path.resolve().is_relative_to(emotion.resolve()) or path.stat().st_size != info['bytes'] or digest(path) != info['sha256']:
                raise ValueError('Emotion resource mismatch')
            paths.append(path)
    for path in sorted(set(paths)):
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Missing or outside allowlisted resource: {path}')
    return sorted(set(paths))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def environment(stage):
    result = {}
    code = """import sys,json,importlib.metadata as m
print(json.dumps({'python':sys.version,'packages':sorted([{'name':d.metadata['Name'],'version':d.version,
'license':d.metadata.get('License-Expression') or d.metadata.get('License'),'home_page':d.metadata.get('Home-page')}
for d in m.distributions()],key=lambda x:x['name'].lower())}))"""
    for name, python in [('ui', stage/'runtimes/ui/python.exe'), ('engine', stage/'engines/verified-v2pro/runtime/python.exe')]:
        probe = subprocess.run([str(python), '-s', '-c', code], cwd=stage, capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
        result[name] = json.loads(probe.stdout)
    ffmpeg = stage/'engines/verified-v2pro/runtime/ffmpeg.exe'
    result['ffmpeg'] = {}
    for option in ('-version', '-L'):
        probe = subprocess.run([str(ffmpeg), option], cwd=stage, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, check=True)
        result['ffmpeg'][option] = probe.stdout + probe.stderr
    return result


def assemble(root, destination, kind, archive=False, compression='stored'):
    root, destination = root.resolve(), destination.resolve()
    if destination == root or root.is_relative_to(destination) or destination.is_relative_to(root):
        raise ValueError('Use an independent staging directory outside the development project')
    if destination.exists() or Path(str(destination)+'.zip').exists():
        raise FileExistsError('Refusing to overwrite an existing candidate')
    paths = select_files(root, kind)
    total = sum(p.stat().st_size for p in paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < total * (3 if archive else 2) + 2*1024**3:
        raise OSError('Insufficient space for staging, archive and verification copy')
    destination.mkdir()
    for index, path in enumerate(paths):
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if index % 5000 == 0:
            print(f'Copied {index}/{len(paths)}', flush=True)
    if kind == 'runtime':
        shutil.copyfile(destination/'config/engine.portable.example.json', destination/'config/engine.local.json')
        shutil.copyfile(destination/'config/workshop.example.json', destination/'config/workshop.local.json')
        emotion = json.loads((destination/'config/emotion-model.example.json').read_text(encoding='utf-8'))
        emotion['manifest_sha256'] = digest(destination/'models/emotion/emotion-zh-v1/model-manifest.json')
        write_json(destination/'config/emotion-model.local.json', emotion)
        # Validate the copied critical resources against the independent pinned list.
        for row in json.loads((destination/'config/environment-resources.json').read_text(encoding='utf-8'))['files']:
            path = destination/'engines/verified-v2pro'/row['path']
            if path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
                raise ValueError('Engine resource hash mismatch: ' + row['path'])
        write_json(destination/'release-environment.json', environment(destination))
    licenses = [p.relative_to(destination).as_posix() for p in allowed_tree(destination)
                if p.name.lower().startswith(('license', 'notice', 'copying', 'copyright'))]
    write_json(destination/'release-licenses.json', {'scope':'bundled-notices-inventory', 'redistribution_review':'pending', 'files':licenses})
    release = json.loads((root/'config/release.json').read_text(encoding='utf-8'))
    write_json(destination/'release-build.json', dict(release, kind=kind, created_at=datetime.now(timezone.utc).isoformat(),
        clean_user_data=True, workshop_auto_start=False, source_worktree='current-files-including-uncommitted-changes'))
    manifest = [{'path':p.relative_to(destination).as_posix(), 'bytes':p.stat().st_size, 'sha256':digest(p)}
                for p in allowed_tree(destination)]
    write_json(destination/'release-manifest.json', {'files':manifest, 'file_bytes':sum(p['bytes'] for p in manifest)})
    result = {'directory':str(destination), 'kind':kind, 'files':len(manifest), 'file_bytes':sum(p['bytes'] for p in manifest),
              'manifest_sha256':digest(destination/'release-manifest.json')}
    if archive:
        target = Path(str(destination)+'.zip')
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED if compression == 'deflated' else zipfile.ZIP_STORED,
                             compresslevel=1 if compression == 'deflated' else None, allowZip64=True) as z:
            for path in allowed_tree(destination):
                z.write(path, arcname=destination.name + '/' + path.relative_to(destination).as_posix())
        result.update(archive=target.name, archive_bytes=target.stat().st_size, archive_sha256=digest(target), compression=compression)
    write_json(destination.parent/(destination.name+'-summary.json'), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('source', 'runtime'), required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--zip', action='store_true')
    parser.add_argument('--compression', choices=('stored', 'deflated'), default='stored')
    args = parser.parse_args()
    assemble(ROOT, args.destination, args.kind, args.zip, args.compression)
