"""Machine-readable probes, executed by the interpreter being diagnosed."""
import argparse
import importlib
import json
import sys
from pathlib import Path

MARKER = 'ENV_SETUP_RESULT='


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['ui', 'model', 'gpu'])
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    result = {'executable': sys.executable, 'prefix': sys.prefix, 'kind': args.kind}
    try:
        if args.kind == 'ui':
            sys.path.insert(0, args.root)
            modules = [importlib.import_module(name) for name in ['gradio', 'pydantic', 'yaml']]
            result['modules'] = {m.__name__: {'file': m.__file__, 'version': getattr(m, '__version__', '')} for m in modules}
            import app
            demo = app.build_app()
            result['components'] = len(demo.config['components'])
        elif args.kind == 'model':
            groups = {
                'inference': ['torch', 'transformers', 'librosa', 'soundfile', 'fastapi', 'scipy', 'sentencepiece', 'text', 'AR'],
                'training': ['pytorch_lightning', 'funasr', 'modelscope', 'yaml', 'tensorboard', 'torchmetrics'],
            }
            result['groups'] = {}
            for group, names in groups.items():
                details = {}
                for name in names:
                    try:
                        module = importlib.import_module(name)
                        details[name] = {'ok': True, 'file': str(getattr(module, '__file__', ''))}
                    except Exception as exc:
                        details[name] = {'ok': False, 'error': str(exc)}
                result['groups'][group] = details
        else:
            import torch
            result.update(torch=torch.__version__, cuda=torch.version.cuda,
                          cuda_available=torch.cuda.is_available())
            if not result['cuda_available']:
                raise RuntimeError('CPU-only Torch or CUDA unavailable')
            result['gpu_name'] = torch.cuda.get_device_name(0)
            result['capability'] = list(torch.cuda.get_device_capability(0))
            x = torch.ones((16, 16), device='cuda')
            value = (x @ x).sum().item()
            torch.cuda.synchronize()
            if value != 4096.0:
                raise RuntimeError('CUDA tensor result mismatch')
            result['tensor_sum'] = value
            result['free_bytes'], result['total_bytes'] = torch.cuda.mem_get_info(0)
        result['ok'] = True
    except Exception as exc:
        result.update(ok=False, error=str(exc))
    print(MARKER + json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
