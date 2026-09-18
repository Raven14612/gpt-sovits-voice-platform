"""Real local workflow in an isolated release validation copy; never use production data indexes.

Reads up to 60 seconds from --audio; resulting test data stays in the validation copy.
Automatic acceptance of ASR text is solely for pipeline testing, not human review.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import wave
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--resume-dataset', help='Retry training using a dataset from a failed run in this validation copy')
    args = parser.parse_args()
    if not (ROOT/'release-build.json').is_file() or not (ROOT/'.validation-copy').is_file():
        raise ValueError('Run only in a separate assembled validation copy marked .validation-copy')
    if (ROOT/'data/index/voices.json').exists():
        raise ValueError('Requires a fresh validation copy, not existing user data')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['MODELSCOPE_OFFLINE'] = '1'
    from services import dataset_service as ds, audio_service, feature_service, training_preparation_service as prep
    from services import voice_service as voices, tts_service, voice_package_service as packages, task_service
    from services.workshop_client import WorkshopClient, load_config
    from services.workshop_runtime import stop_local_services
    from services.wav_service import inspect_wav
    from adapters.inference_runtime import runtime
    from models.schemas import AppError
    evidence = ROOT/'data/logs/diagnostics'/('mvp-workflow-'+uuid4().hex[:8] if args.resume_dataset else 'mvp-workflow')
    evidence.mkdir(parents=True, exist_ok=False)
    report = {'scope':'real_single_machine_gpu_and_http_two_identities', 'human_listening':'NOT_VERIFIED',
              'external_server':'NOT_VERIFIED', 'receiving_machine':'NOT_VERIFIED', 'stages':[]}
    def record(stage, **extra):
        report['stages'].append(dict(stage=stage, **extra))
        (evidence/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(stage, flush=True)
    def succeeded(task):
        if task.status.value != 'succeeded':
            raise RuntimeError(f'{task.stage}: {task.message}')
    try:
        if args.resume_dataset:
            dataset = ds.get_dataset(args.resume_dataset)
            if not dataset or not dataset.feature_manifest:
                raise ValueError('No validated dataset to resume')
            record('reuse_existing_real_features', dataset_id=dataset.dataset_id)
        else:
            sample = evidence/'input.wav'
            with wave.open(str(args.audio), 'rb') as source, wave.open(str(sample), 'wb') as target:
                target.setparams(source.getparams())
                target.writeframes(source.readframes(min(source.getnframes(), source.getframerate()*60)))
            dataset = ds.import_audio(str(sample), 'MVP 隔离验收样本')
            succeeded(audio_service.process_audio(dataset))
            rows = ds.load_corrections(dataset.dataset_id)
            ds.save_corrections(dataset.dataset_id, rows, annotation_name='自动验收标注（未经人工校对）')
            record('real_slice_asr', slices=len(rows))
            succeeded(feature_service.extract_features(dataset.dataset_id))
            record('real_gpu_features')
        voice_id = 'mvp-' + uuid4().hex[:12]
        plan = prep.prepare_training(dataset.dataset_id, voice_id)
        prepared = json.loads(plan.read_text(encoding='utf-8'))
        dataset = ds.get_dataset(prepared['dataset_id'])
        params = prep.training_parameters(plan, dataset, 'MVP 隔离测试音色', 'train-'+uuid4().hex)
        task = voices.train_voice(dataset, voice_id, params)
        prep.finish_training_plan(plan, task)
        succeeded(task)
        record('real_gpu_training', gpt_epochs=15, sovits_epochs=8, batch_size=4, voice_id=voice_id)
        output = ROOT/'data/outputs'/('tts-mvp-'+uuid4().hex+'.wav')
        tts_service.synthesize(voice_id=voice_id, target_text='这是隔离验收生成的新语音，请检查文字和声音是否一致。', output_path=output, port=free_port(), timeout=300)
        runtime.close()
        record('real_gpu_synthesis', wav=inspect_wav(output), output=str(output.relative_to(ROOT)))
        package = packages.export_voice_package(voice_id, '本机隔离验收', '仅用于本机功能验收，不对外发布', '仅限获得作者许可后使用', True)
        config = dict(load_config(), base_url=f'http://127.0.0.1:{free_port()}', auto_start_local=True)
        publisher = WorkshopClient(root=ROOT/'data/tmp/test-publisher', config=config)
        subscriber = WorkshopClient(root=ROOT, config=dict(config, auto_start_local=False))
        uploaded = publisher.upload_voice(package)
        wid = uploaded['id']
        from PIL import Image
        cover = evidence/'cover.png'
        Image.new('RGB', (80,80), '#734535').save(cover)
        publisher.set_cover(wid, cover)
        assert subscriber.list_voices()[0]['can_edit_cover'] is False
        try:
            subscriber.withdraw_voice(wid)
        except AppError as exc:
            assert exc.code == 'WITHDRAW_FORBIDDEN'
        else:
            raise AssertionError('Non-owner withdrawal accepted')
        downloaded = subscriber.download_voice(wid, expected_size=uploaded['package_bytes'], expected_sha256=uploaded['package_sha256'])
        installed = packages.install_voice_package(downloaded, origin_workshop_id=wid)
        publisher.withdraw_voice(wid)
        assert subscriber.list_voices() == []
        stop_local_services()
        record('real_package_export_http_install_withdraw', installed_voice=installed.voice_id)
        # Fresh interpreter proves persisted installation remains usable without workshop access.
        code = """import sys,json
from pathlib import Path
from unittest.mock import patch
from services import tts_service,voice_service,history_service
from services.wav_service import inspect_wav
from adapters.inference_runtime import runtime
voice=voice_service.get_voice(sys.argv[1]); assert voice.status=='verified'
try:
 with patch('services.workshop_client.WorkshopClient._client',side_effect=AssertionError('local synthesis accessed workshop')):
  tts_service.synthesize(voice_id=voice.voice_id,target_text='工坊已经断开，下载的音色依然可以在本机合成。',output_path=Path(sys.argv[2]),port=int(sys.argv[3]),timeout=300)
 print(json.dumps(inspect_wav(Path(sys.argv[2]))))
finally: runtime.close()
"""
        offline_output = ROOT/'data/outputs'/('tts-offline-'+uuid4().hex+'.wav')
        child = subprocess.run([sys.executable, '-s', '-c', code, installed.voice_id, str(offline_output), str(free_port())],
                               cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=420)
        (evidence/'offline-synthesis.log').write_text(child.stdout+child.stderr, encoding='utf-8')
        if child.returncode:
            raise RuntimeError('Offline synthesis after restart failed: '+child.stderr[-2000:])
        record('real_gpu_offline_synthesis_after_restart', wav=inspect_wav(offline_output), output=str(offline_output.relative_to(ROOT)))
        voices.set_voice_deleted(installed.voice_id, True)
        assert voices.get_voice(installed.voice_id).status == 'deleted'
        voices.set_voice_deleted(installed.voice_id, False)
        assert voices.get_voice(installed.voice_id).status == 'verified'
        record('reversible_local_uninstall_restore')
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        runtime.close()
        stop_local_services()
        (evidence/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
