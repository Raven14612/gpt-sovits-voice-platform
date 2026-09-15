from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from adapters.gpt_sovits import GPTSoVITSAdapter
from models.schemas import EngineConfig


class AdapterTests(TestCase):
    def test_api_command_uses_argument_array(self):
        with TemporaryDirectory() as d:
            root = Path(d); py = root / "python.exe"
            py.touch(); gpt = root / "g.ckpt"; gpt.touch(); sovits = root / "s.pth"; sovits.touch(); wav = root / "r.wav"; wav.touch()
            adapter = GPTSoVITSAdapter(EngineConfig(engine_root=root, python_path=py))
            cmd = adapter.api_command(gpt_path=gpt, sovits_path=sovits, refer_wav=wav, refer_text="参考", target_text="目标")
            self.assertIn("api.py", cmd); self.assertNotIn(" ".join(cmd), cmd)
