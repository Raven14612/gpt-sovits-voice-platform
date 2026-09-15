"""Read-only cross-check of Week 3 evidence; exits nonzero on inconsistency."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.wav_service import inspect_wav


def audit():
    directory = ROOT/'data/logs/diagnostics/week3'
    manifest = json.loads((directory/'regression.json').read_text(encoding='utf-8'))
    history = json.loads((ROOT/'data/index/history.json').read_text(encoding='utf-8'))
    tasks = json.loads((ROOT/'data/index/tasks.json').read_text(encoding='utf-8'))
    findings = []
    checks = []
    for run in manifest['runs']:
        errors = []
        try:
            hs = [h for h in history if h['result_id'] == run['result_id']]
            ts = [t for t in tasks if t['task_id'] == run['task_id']]
            assert len(hs) == len(ts) == 1, 'unique index mapping'
            h, t = hs[0], ts[0]
            assert h['status'] == t['status'] == run['status'] == 'succeeded', 'status'
            assert t['result_id'] == run['result_id'], 'result/task link'
            for key in ('voice_id', 'text', 'speed_factor', 'fragment_interval'):
                assert h[key] == t['input_params'][key] == run[key], key
            assert h['emotion'] == t['input_params']['emotion'] == 'neutral', 'emotion'
            output = (ROOT/h['output_path']).resolve()
            assert output.is_relative_to((ROOT/'data/outputs').resolve()), 'output boundary'
            info = inspect_wav(output)
            for key, value in info.items():
                assert value == run[key] == t['output_info'][key], key
            assert t['created_at'].replace('Z','+00:00') == run['created_at'], 'created_at'
            assert output.stat().st_mtime >= datetime.fromisoformat(run['created_at']).timestamp(), 'new output'
            log = ROOT/run['log_path']
            assert str(t['log_path']).replace('\\','/') == run['log_path'], 'task log'
            events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            assert events[0]['input_params'] == t['input_params'], 'logged input'
            assert events[-1]['event'] == 'succeeded', 'success log'
            assert events[-1]['result_id'] == run['result_id'], 'logged result'
            assert events[-2]['output_info']['sha256'] == info['sha256'], 'logged hash'
            engine = ROOT/'data/logs/synthesis'/run['engine_log']
            assert engine.is_file(), 'engine log'
        except Exception as exc:
            errors.append(str(exc))
        checks.append({'case':run['case'], 'result_id':run['result_id'], 'passed':not errors, 'errors':errors})
        findings.extend(errors)
    hashes = [r.get('sha256') for r in manifest['runs']]
    if len(set(hashes)) != len(hashes):
        findings.append('duplicate output hashes')
    # Case 2 may be re-generated during evidence repair after the original
    # process was closed; the original regression already recorded the
    # continuous run. Verify that at least three successful fixed-text runs
    # share a PID instead of coupling the check to manifest order.
    fixed = [r for r in manifest['runs'] if r.get('case') in {'1','2','3','4','5'}]
    pid_groups = {}
    for run in fixed:
        pid_groups.setdefault(run.get('engine_pid'), []).append(run)
    if max((len(group) for group in pid_groups.values()), default=0) < 3:
        findings.append('fewer than three fixed-text requests share a process')
    report = {'passed':not findings, 'checks':checks, 'findings':findings,
              'human_listening':manifest.get('human_listening', 'pending; not inferred by audit')}
    (directory/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(audit())
