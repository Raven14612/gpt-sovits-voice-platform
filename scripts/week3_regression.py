"""Run real configured GPU synthesis; no fixtures or prerecorded output are used."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import tts_service, task_service
from adapters.inference_runtime import runtime

TEXTS = [
    '今天的天气很好，我们一起去公园散步。',
    '请先选择音色，再输入需要朗读的文字。',
    '图书馆里很安静。窗外的树叶正在轻轻摇动。',
    '欢迎使用本地语音合成工具，希望这段声音能帮助你。',
    '完成练习后，请保存结果，并检查每一句话是否清楚。',
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    evidence = ROOT/'data/logs/diagnostics/week3'
    evidence.mkdir(parents=True, exist_ok=True)
    manifest = evidence/'regression.json'
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'runs': [],
              'pause_control': 'unsupported; UI disabled and service rejects changes',
              'human_listening': 'pending'}
    cases = [(str(i+1), text, 'citlali' if i == 3 else 'buer-w2-project', 1.0)
             for i, text in enumerate(TEXTS)]
    cases += [('speed-slow', TEXTS[2], 'buer-w2-project', 0.8),
              ('speed-fast', TEXTS[2], 'buer-w2-project', 1.2)]
    try:
        for case, text, voice, speed in cases:
            result_id = f'tts-w3-{case}-{uuid4().hex}'
            started = time.monotonic()
            output = ROOT/'data/outputs'/f'{result_id}.wav'
            print(f'START {case}: {voice}, speed={speed}', flush=True)
            try:
                tts_service.synthesize(voice_id=voice, target_text=text, speed_factor=speed,
                                       output_path=output, timeout=args.timeout)
                task = next(t for t in task_service.list_tasks() if t.result_id == result_id)
                report['runs'].append({'case': case, 'result_id': result_id,
                    'task_id': task.task_id, 'voice_id': voice, 'text': text,
                    'speed_factor': speed, 'fragment_interval': 0.3,
                    'created_at': task.created_at.isoformat(),
                    'elapsed_seconds': round(time.monotonic()-started, 3),
                    'log_path': task.log_path.relative_to(ROOT).as_posix(),
                    **{key: value for key, value in task.output_info.items() if key != "weights"}, 'status': task.status.value})
                print(f'OK {case}: {task.output_info["duration_seconds"]:.2f}s audio; {time.monotonic()-started:.1f}s elapsed; pid={task.output_info.get("engine_pid")}', flush=True)
            except Exception as exc:
                report['runs'].append({'case': case, 'result_id': result_id, 'status': 'failed', 'error': str(exc)})
                raise
            finally:
                manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        runtime.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
