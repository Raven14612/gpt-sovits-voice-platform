"""Runs only in the model interpreter, using tiny constructed checkpoints."""
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import types

import torch

module = types.ModuleType('utils')
sys.modules['utils'] = module
exec('class HParams:\n    pass\nclass UnknownConfig:\n    pass\n', module.__dict__)
sanitize = runpy.run_path(str(Path(sys.argv[1]) / 'scripts/sanitize_voice_checkpoint.py'))['sanitize']


def bag(**values):
    obj = module.HParams()
    obj.__dict__.update(values)
    return obj


with TemporaryDirectory() as directory:
    root = Path(directory)
    source = root / 'legacy.pth'
    config = bag(data=bag(filter_length=2048, sampling_rate=32000, hop_length=640,
                         win_length=2048, n_speakers=1), train=bag(segment_size=20480),
                 model=bag(version='v2Pro'), output_dir='C:/private/training')
    torch.save({'config': config, 'weight': {'fixture': torch.ones(2)}}, source)
    with source.open('r+b') as handle:
        handle.write(b'05')
    before = source.read_bytes()
    target = root / 'safe.pth'
    sanitize(source, target, 'sovits')
    assert source.read_bytes() == before
    payload = target.read_bytes()
    assert payload[:2] == b'05'
    normalized = root / 'normalized.pth'
    normalized.write_bytes(b'PK' + payload[2:])
    result = torch.load(normalized, weights_only=True, map_location='cpu')
    assert type(result['config']) is dict
    assert type(result['config']['data']) is dict
    assert 'output_dir' not in result['config']
    assert torch.equal(result['weight']['fixture'], torch.ones(2))
    assert result['weight']['fixture'].device.type == 'cpu'
    # Other pickle globals must remain forbidden.
    invalid = root / 'unknown.pth'
    torch.save({'config': module.UnknownConfig(), 'weight': {'fixture': torch.ones(1)}}, invalid)
    try:
        sanitize(invalid, root / 'forbidden.pth', 'sovits')
    except Exception:
        pass
    else:
        raise AssertionError('Unknown config global was accepted')
    assert not (root / 'forbidden.pth').exists()
    # An allowlisted bag still cannot hide a cycle.
    cyclic = bag()
    cyclic.loop = cyclic
    torch.save({'config': cyclic, 'weight': {'fixture': torch.ones(1)}}, invalid)
    try:
        sanitize(invalid, root / 'cycle.pth', 'sovits')
    except ValueError:
        pass
    else:
        raise AssertionError('Cyclic config was accepted')
    print('PASS: legacy HParams -> plain dictionaries, CPU only, unknown globals/cycles rejected')
