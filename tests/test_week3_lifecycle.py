"""Fault tests use synthetic PCM only inside temporary directories, never GPU evidence."""
import json
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from models.schemas import AppError, GenerationRecord, TaskRecord, TaskStatus, VoiceProfile, EmotionReference
from services import history_service as history, tts_service as tts, task_service as tasks
from services.wav_service import inspect_wav
from adapters.inference_runtime import InferenceRuntime


def pcm(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 160)
    return path


class HistoryEnvironment(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.output = self.root / 'data/outputs'
        self.index = self.root / 'data/index/history.json'
        for name, value in [('PROJECT_ROOT', self.root), ('OUTPUT_ROOT', self.output), ('HISTORY_INDEX', self.index)]:
            self.stack.enter_context(patch.object(history, name, value))

    def record(self, name='r'):
        return GenerationRecord(result_id=name, voice_id='v', text='测试',
                                output_path=pcm(self.output / f'{name}.wav'), status='succeeded')


class HistoryLifecycleTests(HistoryEnvironment):
    def test_concurrent_upserts_and_idempotency(self):
        records = [self.record(str(i)) for i in range(12)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(history.add_history, records * 2))
        self.assertEqual(len(history.list_history()), 12)
        self.assertEqual(history.reuse_history('1')['text'], '测试')

    def test_corrupt_index_preserved(self):
        self.index.parent.mkdir(parents=True)
        self.index.write_text('{broken', encoding='utf-8')
        with self.assertRaises(AppError):
            history.add_history(self.record())
        self.assertEqual(self.index.read_text(), '{broken')

    def test_external_truncated_shared_and_conflicting_files_rejected(self):
        record = self.record()
        history.add_history(record)
        for update in ({'result_id': 'other'}, {'output_path': pcm(self.output/'other.wav')},
                       {'output_path': pcm(self.root/'outside.wav')}):
            with self.assertRaises(AppError):
                history.add_history(record.model_copy(update=update))
        record.output_path.write_bytes(b'RIFF')
        with self.assertRaises(AppError):
            history.add_history(record)
        self.assertEqual(history.list_history(), [])

    def test_delete_and_missing_file(self):
        record = self.record()
        history.add_history(record)
        self.assertTrue(history.delete_history('r'))
        self.assertFalse(record.output_path.exists())
        history.add_history(self.record())
        record.output_path.unlink()
        self.assertTrue(history.delete_history('r'))
        self.assertEqual(history.list_history(), [])

    def test_delete_index_failure_rolls_back(self):
        record = self.record()
        history.add_history(record)
        with patch.object(history, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(AppError):
                history.delete_history('r')
        self.assertTrue(record.output_path.is_file())
        self.assertIsNotNone(history.get_result_output('r'))

    def test_delete_file_failure_keeps_record(self):
        history.add_history(self.record())
        with patch.object(history.os, 'replace', side_effect=PermissionError('in use')):
            with self.assertRaises(AppError):
                history.delete_history('r')
        self.assertIsNotNone(history.get_result_output('r'))

    def test_crash_recovery_restores_deletion_and_cleans_only_owned_temporary(self):
        record = self.record()
        history.add_history(record)
        record.output_path.rename(record.output_path.with_suffix('.wav.deleting'))
        partial = self.output / 'tts-interrupted.wav.part'
        partial.write_bytes(b'incomplete')
        unrelated = self.output / 'user.part'
        unrelated.write_bytes(b'keep')
        report = history.recover_history()
        self.assertEqual(report['restored'], ['r.wav'])
        self.assertFalse(partial.exists())
        self.assertTrue(unrelated.exists())
        record.output_path.unlink()
        self.assertEqual(history.recover_history()['invalid_results'], ['r'])
        self.assertEqual(history.list_history(), [])


class TTSLifecycleTests(HistoryEnvironment):
    def setUp(self):
        super().setUp()
        self.task_index = self.root / 'data/index/tasks.json'
        self.stack.enter_context(patch.object(tts, 'PROJECT_ROOT', self.root))
        self.stack.enter_context(patch.object(tts, 'LOG_ROOT', self.root/'data/logs/synthesis'))
        self.stack.enter_context(patch.object(tts, 'upsert_task', side_effect=lambda t: tasks.upsert_task(t, self.task_index)))
        self.config = self.root/'config.json'
        self.config.write_text(json.dumps({'engine_root': str(self.root), 'python_path': str(self.root/'python')}))
        self.voice = VoiceProfile(voice_id='v', display_name='v', feature_name='v', dataset_id='d',
            gpt_weight=self.root/'g', sovits_weight=self.root/'s', engine_profile='test', status='verified',
            references=[EmotionReference(emotion='neutral', audio_path=pcm(self.root/'ref.wav'), prompt_text='参考')])
        self.stack.enter_context(patch.object(tts, 'get_voice_profile', return_value=self.voice))

    def call(self, **kwargs):
        return tts.synthesize(voice_id='v', target_text='测试', output_path=self.output/'tts-r.wav',
                              config_path=self.config, **kwargs)

    def test_success_has_params_log_hash_and_history(self):
        adapter = Mock(last_inference={'engine_pid': 123})
        adapter.synthesize.side_effect = lambda **kw: pcm(kw['output_path'])
        with patch.object(tts, 'GPTSoVITSAdapter', return_value=adapter):
            self.call()
        task = tasks.list_tasks(self.task_index)[0]
        self.assertEqual(task.status, TaskStatus.SUCCEEDED)
        self.assertEqual(task.input_params['text'], '测试')
        self.assertEqual(task.output_info['sha256'], inspect_wav(self.output/'tts-r.wav')['sha256'])
        self.assertTrue(task.log_path.is_file())
        self.assertEqual(len(history.list_history()), 1)

    def test_gpu_busy_is_failed_and_keeps_other_lock(self):
        tasks.try_acquire_gpu()
        try:
            with self.assertRaises(AppError) as caught:
                self.call()
            self.assertEqual(caught.exception.code, 'GPU_BUSY')
            self.assertTrue(tasks.is_gpu_busy())
            self.assertEqual(tasks.list_tasks(self.task_index)[0].status, TaskStatus.FAILED)
        finally:
            tasks.release_gpu()

    def test_engine_failure_invalid_pcm_and_history_failure_never_publish(self):
        for behavior in ('exit', 'invalid', 'history'):
            adapter = Mock()
            def operation(**kw):
                if behavior == 'exit':
                    raise AppError('ENGINE_EXITED', 'exited')
                if behavior == 'invalid':
                    kw['output_path'].parent.mkdir(parents=True, exist_ok=True)
                    kw['output_path'].write_bytes(b'bad')
                    return kw['output_path']
                return pcm(kw['output_path'])
            adapter.synthesize.side_effect = operation
            adapter.last_inference = {}
            with patch.object(tts, 'GPTSoVITSAdapter', return_value=adapter), \
                    patch.object(history, 'add_history', side_effect=AppError('HISTORY_INDEX_INVALID', 'bad')):
                with self.assertRaises(AppError):
                    self.call()
            self.assertFalse(tasks.is_gpu_busy())
            self.assertFalse((self.output/'tts-r.wav').exists())
            self.assertEqual(history.list_history(), [])
        self.assertTrue(all(t.status == TaskStatus.FAILED for t in tasks.list_tasks(self.task_index)))

    def test_unsupported_pause_and_long_text_fail_before_engine(self):
        with patch.object(tts, 'GPTSoVITSAdapter') as adapter:
            with self.assertRaises(AppError) as caught:
                self.call(fragment_interval=1.0)
            self.assertEqual(caught.exception.code, 'UNSUPPORTED_PARAMETER')
            adapter.assert_not_called()


class RuntimeTests(TestCase):
    def test_same_process_reused_and_weight_switch_checked(self):
        runtime = InferenceRuntime()
        adapter = Mock()
        adapter.config.engine_root = Path('.')
        adapter.config.python_path = Path('python')
        runtime.key = (str(Path('.').resolve()), str(Path('python').resolve()), 9888)
        runtime.weights = ('g', 's')
        runtime.log_path = Path('engine.log')
        runtime.process = Mock(pid=42)
        runtime.process.poll.return_value = None
        with patch.object(runtime, 'request', return_value=b'{"code":0}') as request:
            runtime.ensure(adapter, [], ('g', 's'), 9888, 1e20, Path('.'))
            self.assertEqual(request.call_count, 1)
            runtime.ensure(adapter, [], ('g2', 's2'), 9888, 1e20, Path('.'))
            self.assertEqual(request.call_args.args[1], '/set_model')
            self.assertEqual(runtime.weights, ('g2', 's2'))
        runtime.close()
        self.assertIsNone(runtime.process)

    def test_close_kills_after_terminate_timeout(self):
        import subprocess
        runtime = InferenceRuntime()
        process = Mock()
        runtime.process = process
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('api', 10), 0]
        runtime.close()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_failed_close_keeps_process_handle_for_retry(self):
        runtime = InferenceRuntime()
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError('temporary termination failure')
        runtime.process = process
        with self.assertRaises(OSError):
            runtime.close()
        self.assertIs(runtime.process, process)
        process.terminate.side_effect = None
        runtime.close()
        self.assertIsNone(runtime.process)

    def test_startup_exit_timeout_and_busy_port(self):
        import time
        with TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = Mock()
            adapter.config.engine_root = root
            adapter.config.python_path = root/'python'
            adapter.audio_environment.return_value = {}
            for failure in ('exit', 'timeout', 'busy'):
                runtime = InferenceRuntime()
                process = Mock(pid=123)
                process.poll.return_value = 1 if failure == 'exit' else None
                with patch('adapters.inference_runtime.socket.socket') as socket, \
                        patch('adapters.inference_runtime.subprocess.Popen', return_value=process):
                    socket.return_value.__enter__.return_value.connect_ex.return_value = 0 if failure == 'busy' else 1
                    with self.assertRaises(AppError) as caught:
                        runtime.ensure(adapter, ['python'], ('g','s'), 9888, time.monotonic()-1, root)
                    self.assertEqual(caught.exception.code, {'exit':'ENGINE_EXITED','timeout':'ENGINE_TIMEOUT','busy':'ENGINE_PORT_BUSY'}[failure])
                    self.assertIsNone(runtime.process)
                runtime.close()
