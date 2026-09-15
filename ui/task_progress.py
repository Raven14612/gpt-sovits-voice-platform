"""One lightweight, task-driven waiting indicator for the five-page workspace."""
from datetime import datetime, timezone
from html import escape

import gradio as gr

from models.schemas import AppError, TaskStatus
from services import task_service

KINDS = {"process_audio": "音频切分与识别", "extract_features": "特征提取", "train_features": "特征提取",
         "train_voice": "音色训练", "synthesis": "语音合成"}
STAGES = {"waiting": "等待执行", "validating": "检查输入", "slicing": "切分音频",
          "asr": "识别文本", "feature_text": "提取文本特征", "feature_hubert": "提取声学特征",
          "feature_semantic": "提取语义特征", "train_gpt": "训练 GPT 权重",
          "train_sovits": "训练 SoVITS 权重", "packaging": "归档音色权重", "synthesis": "生成语音"}
# Animation pacing only, never an estimate of remaining model execution time.
DURATIONS = {"process_audio": 90, "extract_features": 180, "train_features": 180,
             "train_voice": 600, "synthesis": 30}


def progress_html(snapshot, elapsed=0):
    status = snapshot["status"]
    labels = {"idle": "空闲", "pending": "准备中", "running": "执行中",
              "succeeded": "已完成", "failed": "失败", "cancelled": "已取消", "unknown": "状态暂不可用"}
    live = status in {"pending", "running"}
    prefix = "当前任务" if live else "最近任务" if snapshot["id"] else "任务状态"
    label = f'{prefix} · {snapshot["title"]} · {labels[status]}'
    duration = DURATIONS.get(snapshot["kind"], 90)
    value = ' aria-valuenow="100"' if status == "succeeded" else ''
    hint = "模拟进度，不代表实际完成比例；任务成功后才会填满。" if live else snapshot["detail"]
    detail = snapshot["detail"] if live else ""
    return (f'<section class="task-progress-panel" data-state="{status}" aria-busy="{str(live).lower()}">'
            f'<div class="task-progress-heading" role="status"><span class="task-progress-dot" aria-hidden="true"></span>'
            f'<strong>{escape(label)}</strong><span class="task-progress-stage">{escape(detail)}</span></div>'
            f'<div class="task-progress-track" role="progressbar" aria-label="{escape(label)}"'
            f' aria-valuemin="0" aria-valuemax="100"{value} aria-valuetext="{escape(hint)}">'
            f'<div class="task-progress-fill" style="--progress-duration:{duration}s;--progress-delay:-{max(0, elapsed):.2f}s"></div></div>'
            f'<div class="task-progress-note">{escape(hint)}</div></section>')


def refresh_progress(previous, submitting=False, tts_submitting=False, notice=""):
    """Reuse the UI's one-second timer; only redraw when task metadata changes."""
    snapshot = {"id": "", "kind": "", "status": "idle", "title": "本地任务",
                "detail": "等待提交音频处理、特征提取、训练或合成任务。"}
    elapsed = 0
    submitting = bool(submitting or tts_submitting)
    baseline = previous.get("_baseline", "") if previous else ""
    try:
        records = sorted(task_service.list_tasks(strict=True), key=lambda t: t.updated_at, reverse=True)
        live = next((t for t in records if t.status in {TaskStatus.PENDING, TaskStatus.RUNNING}), None)
        latest = records[0] if records else None
        # Remember the old terminal record for this submission. It must not
        # appear as 100% while the next job is still validating its inputs.
        # A newly finished record wins even if the generator's flag lags behind.
        if submitting and not (previous or {}).get("_submitting"):
            if live or (previous and previous.get("status") in {"pending", "running"}):
                baseline = ""
            else:
                baseline = previous.get("id", "") if previous else (latest.task_id if latest else "")
        if live or (latest and (not submitting or latest.task_id != baseline)):
            task = live or latest
            snapshot = {"id": task.task_id, "kind": task.kind, "status": task.status.value,
                        "title": KINDS.get(task.kind, "本地任务"),
                        "detail": STAGES.get(task.stage, task.stage) if live else task.message}
            elapsed = (datetime.now(timezone.utc) - task.created_at).total_seconds()
        elif submitting:
            snapshot.update(id="preparing", status="pending", title="语音合成" if tts_submitting else "本地任务",
                            detail="正在提交并检查输入。" if tts_submitting else (notice or "正在准备任务。"))
    except (AppError, OSError):
        snapshot.update(status="unknown", detail="暂时无法读取任务状态，请查看任务与日志。")
    snapshot.update(_submitting=submitting, _baseline=baseline if submitting else "")
    if snapshot == previous:
        return gr.skip(), gr.skip()
    return progress_html(snapshot, elapsed), snapshot
