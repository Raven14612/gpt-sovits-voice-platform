from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

import gradio as gr

from models.schemas import AppError, TaskRecord, TaskStatus
from ui.task_progress import refresh_progress


class TaskProgressTests(TestCase):
    def poll(self, records, previous=None, **kwargs):
        with patch("ui.task_progress.task_service.list_tasks", return_value=records):
            return refresh_progress(previous, **kwargs)

    def task(self, task_id="job", status=TaskStatus.RUNNING, **kwargs):
        return TaskRecord(task_id=task_id, kind="synthesis", status=status, **kwargs)

    def test_live_task_wins_over_newer_terminal_record(self):
        live = self.task(stage="synthesis")
        failure = self.task("other", TaskStatus.FAILED)
        html, state = self.poll([live, failure])
        self.assertEqual(state["id"], "job")
        self.assertIn("生成语音", html)
        self.assertNotIn('aria-valuenow="100"', html)

    def test_pending_before_task_registration(self):
        html, state = self.poll([], submitting=True, notice="正在准备训练输入。")
        self.assertEqual(state["status"], "pending")
        self.assertIn("正在准备训练输入", html)
        self.assertNotIn('aria-valuenow="100"', html)

    def test_second_submission_hides_old_success_until_new_record_exists(self):
        old = self.task("old", TaskStatus.SUCCEEDED)
        _, state = self.poll([old])
        html, state = self.poll([old], state, tts_submitting=True)
        self.assertEqual(state["status"], "pending")
        self.assertIn("语音合成", html)
        self.assertNotIn('aria-valuenow="100"', html)
        self.assertEqual(self.poll([old], state, tts_submitting=True), (gr.skip(), gr.skip()))
        fast = self.task("fast", TaskStatus.SUCCEEDED)
        html, state = self.poll([old, fast], state, tts_submitting=True)
        self.assertEqual(state["id"], "fast")
        self.assertIn('aria-valuenow="100"', html)
        self.assertEqual(self.poll([old, fast], state, tts_submitting=True), (gr.skip(), gr.skip()))

    def test_first_poll_during_submission_does_not_show_stale_success(self):
        _, state = self.poll([self.task(status=TaskStatus.SUCCEEDED)], tts_submitting=True)
        self.assertEqual(state["status"], "pending")

    def test_success_requires_success_record_even_when_submission_flag_lags(self):
        live = self.task()
        _, state = self.poll([live], tts_submitting=True)
        self.assertEqual(self.poll([live], state, tts_submitting=True), (gr.skip(), gr.skip()))
        done = live.model_copy(update={"status": TaskStatus.SUCCEEDED})
        html, state = self.poll([done], state, tts_submitting=True)
        self.assertIn('aria-valuenow="100"', html)
        self.assertEqual(state["status"], "succeeded")

    def test_failure_and_cancellation_never_report_completion(self):
        for status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
            with self.subTest(status=status):
                html, state = self.poll([self.task(status=status, message="测试停止")])
                self.assertEqual(state["status"], status.value)
                self.assertIn("测试停止", html)
                self.assertNotIn('aria-valuenow="100"', html)
                self.assertIn('aria-busy="false"', html)

    def test_index_error_does_not_claim_idle_or_success(self):
        with patch("ui.task_progress.task_service.list_tasks", side_effect=AppError("INDEX", "broken")):
            html, state = refresh_progress(None)
        self.assertEqual(state["status"], "unknown")
        self.assertIn("暂时无法读取", html)

    def test_unchanged_snapshot_skips_render_and_preserves_animation(self):
        task = self.task()
        _, state = self.poll([task])
        self.assertEqual(self.poll([task], state), (gr.skip(), gr.skip()))

    def test_stage_change_resumes_animation_at_elapsed_time(self):
        task = self.task(created_at=datetime.now(timezone.utc) - timedelta(seconds=40))
        _, state = self.poll([task])
        html, _ = self.poll([task.model_copy(update={"stage": "synthesis"})], state)
        self.assertRegex(html, r"--progress-delay:-40\.\d+s")
        self.assertNotIn('aria-valuenow="100"', html)

    def test_task_messages_are_escaped(self):
        html, _ = self.poll([self.task(status=TaskStatus.FAILED, message='<script>alert("x")</script>')])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_all_gpu_task_kinds_have_human_readable_labels(self):
        for kind in ["process_audio", "extract_features", "train_features", "train_voice", "synthesis"]:
            with self.subTest(kind=kind):
                task = self.task().model_copy(update={"kind": kind})
                _, state = self.poll([task])
                self.assertNotEqual(state["title"], "本地任务")
