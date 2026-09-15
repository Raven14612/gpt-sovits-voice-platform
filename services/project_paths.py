"""Resolve paths from the application root, including preserved pre-move records."""
from pathlib import Path
import json
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_project_path(value, *, root=None):
    root = (Path(root) if root is not None else PROJECT_ROOT).resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        return (root / path).resolve()
    mapping = root / "config/path-migration.json"
    if mapping.is_file():
        aliases = json.loads(mapping.read_text(encoding="utf-8"))["aliases"]
        aliases = sorted(aliases, key=lambda item: len(Path(item["old_root"]).parts), reverse=True)
        for alias in aliases:
            target = (root / alias["new_relative_root"]).resolve()
            if Path(alias["new_relative_root"]).is_absolute() or not target.is_relative_to(root):
                raise ValueError("Migration alias must point inside the project")
            try:
                suffix = path.resolve().relative_to(Path(alias["old_root"]).resolve())
            except ValueError:
                continue
            resolved = (target / suffix).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("Migrated path escapes the project")
            return resolved
    return path.resolve()


def stored_project_path(value, *, root=None):
    root = (Path(root) if root is not None else PROJECT_ROOT).resolve()
    path = resolve_project_path(value, root=root)
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def project_environment(*, root=None, python=None, engine_root=None):
    """Keep subprocess imports and writable caches independent of the caller."""
    root = (Path(root) if root is not None else PROJECT_ROOT).resolve()
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX"):
        env.pop(key, None)
    locations = {"TEMP": "data/tmp", "TMP": "data/tmp", "TMPDIR": "data/tmp",
                 "GRADIO_TEMP_DIR": "data/tmp/gradio", "HF_HOME": "data/cache/huggingface",
                 "MODELSCOPE_CACHE": "data/cache/modelscope", "TORCH_HOME": "data/cache/torch",
                 "XDG_CACHE_HOME": "data/cache", "NUMBA_CACHE_DIR": "data/cache/numba"}
    for key, relative in locations.items():
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONNOUSERSITE="1",
               GRADIO_ANALYTICS_ENABLED="False")
    paths = []
    if python:
        paths.append(str(Path(python).resolve().parent))
    if engine_root:
        engine_root = Path(engine_root).resolve()
        paths.append(str(engine_root))
        paths.append(str(engine_root / "runtime"))
        env["PYTHONPATH"] = os.pathsep.join([str(engine_root), str(engine_root / "GPT_SoVITS")])
    env["PATH"] = os.pathsep.join([*paths, env.get("PATH", "")])
    return env
