"""S5 optional real synthesis. This is separate from environment diagnostics."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', required=True)
    parser.add_argument('--port', type=int, default=9988)
    parser.add_argument('--text', default='环境检查已经完成，现在可以开始新的语音任务。')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    from services import tts_service, task_service
    from services.wav_service import inspect_wav
    from services.path_migration import atomic_write, encoded
    from adapters.inference_runtime import runtime
    output = ROOT/'data/outputs'/('tts-s5-'+uuid4().hex+'.wav')
    report = {'scope':'actual_synthesis_only', 'training_executed':False,
              'synthesis_executed':True, 'voice_id':args.voice, 'human_listening':'NOT_VERIFIED'}
    try:
        tts_service.synthesize(voice_id=args.voice, target_text=args.text, output_path=output,
                              port=args.port, timeout=240)
        task = next(t for t in task_service.list_tasks() if t.result_id == output.stem)
        report.update(status='PASS', output=str(output.relative_to(ROOT)), wav=inspect_wav(output),
                      task=task.model_dump(mode='json'))
        return 0
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        return 1
    finally:
        runtime.close()
        atomic_write(args.report, encoded(report))
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
