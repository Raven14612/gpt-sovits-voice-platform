from __future__ import annotations

import gradio as gr

from services.engine_service import probe_engine
from services.task_service import recovery_notice
from ui.audio_page import render_audio_page
from ui.result_page import refresh_results, render_result_page
from ui.tts_page import render_tts_page, submission_availability
from services import history_service, voice_service
from models.schemas import AppError
from ui.voice_page import render_voice_page, voice_choices
from ui.audio_page import dataset_choices
from ui.task_status import refresh_status, refresh_task_picker, saved_task_choices
from ui.task_progress import refresh_progress
from ui.workshop_page import render_workshop_page, refresh_workshop
from ui.help import render_help

PAGE_COUNT = 6


def _status_markdown() -> str:
    status = probe_engine()
    symbol = "🟢" if status.available else "🟡"
    gpu = f"\n\nGPU：{status.gpu_name}" if status.gpu_name else ""
    notice = recovery_notice()
    extra = f"\n\n⚠️ {notice}" if notice else ""
    return f"### 环境状态\n\n{symbol} {status.message}{gpu}{extra}"


def _switch_page(index: int):
    return (tuple(gr.update(visible=position == index) for position in range(PAGE_COUNT))
            + tuple(gr.update(variant="primary" if position == index else "secondary") for position in range(PAGE_COUNT)))


def reuse_to_tts(result_id):
    try:
        record = history_service.reuse_history(result_id)
        voice = voice_service.get_voice(record["voice_id"])
        available = voice is not None and voice.status == "verified"
        emotions = [ref.emotion for ref in voice.references] if available else []
        selected = record["voice_id"] if available else None
        emotion = record["emotion"] if record["emotion"] in emotions else (emotions[0] if emotions else None)
        return (selected, gr.update(choices=voice_choices(), value=selected),
                record["text"], gr.update(choices=emotions, value=emotion, interactive=bool(emotions)),
                record["speed_factor"], gr.update(value=record["fragment_interval"], interactive=False),
                "参数已回填；固定停顿不可调整。" if available else "文本和参数已回填；原音色组已删除，请另选音色组。") + _switch_page(2)
    except AppError as exc:
        return (gr.skip(),) * 6 + (f"{exc.code}：{exc.message}",) + (gr.skip(),) * (2 * PAGE_COUNT)


def show_synthesis_result(result_id):
    if not result_id:
        return (gr.skip(),) * (3 + 2 * PAGE_COUNT)
    return refresh_results(result_id) + _switch_page(3)


def render_root_layout() -> None:
    state = {key: gr.State(value=None) for key in (
        "selected_dataset", "selected_slice", "selected_voice", "active_task", "current_result", "reuse_text", "reuse_emotion", "reuse_speed", "reuse_interval")}
    state["submitting"] = gr.State(False)
    state["tts_submitting"] = gr.State(False)
    state["notice"] = gr.State("")

    with gr.Row(elem_id="topbar"):
        gr.Markdown("# 小渡鸦的语音合成平台哟", elem_id="brand-title")
        gr.Markdown("MVP 版本 · 仅面向 NVIDIA RTX 50 系 Windows 电脑", elem_id="scope-badge")

    with gr.Row(elem_id="app-shell"):
        with gr.Column(scale=0, min_width=220, elem_id="sidebar"):
            audio_button = gr.Button("音频数据处理", variant="primary")
            voice_button = gr.Button("音色训练与仓库")
            tts_button = gr.Button("文本生成语音")
            result_button = gr.Button("合成结果管理")
            task_button = gr.Button("任务与日志")
            workshop_button = gr.Button("音色创意工坊")
            gr.Markdown(_status_markdown(), elem_id="environment-status")

        with gr.Column(scale=1, min_width=0, elem_id="page-content"):
            initial_progress, initial_snapshot = refresh_progress(None)
            progress = gr.HTML(initial_progress, elem_id="task-progress-strip", padding=False)
            progress_snapshot = gr.State(initial_snapshot)
            with gr.Column(visible=True) as audio_page:
                audio_datasets, audio_submit = render_audio_page(state)
            with gr.Column(visible=False) as voice_page:
                voice_datasets, voice_submit, voices, voice_library = render_voice_page(state)
            with gr.Column(visible=False) as tts_page:
                tts_refs = render_tts_page(state)
                tts_voices = tts_refs["voices"]
            with gr.Column(visible=False) as result_page:
                results, result_audio, result_message, reuse_button = render_result_page(state)

            with gr.Column(visible=False, elem_id="task-page") as task_page:
                gr.Markdown("## 任务与日志")
                task_picker = gr.Dropdown(label="已保存任务", choices=saved_task_choices(), interactive=True)
                refresh_tasks = gr.Button("刷新任务列表", size="sm")
                gr.Markdown("选择任务查看状态和日志；有新任务时点击刷新任务列表。")
                status = gr.Textbox(label="任务状态", value="当前没有任务。", lines=4, interactive=False, elem_classes=["rj-readout"])
                stages = gr.Dataframe(headers=["阶段", "退出码", "检查信息", "日志文件"], value=[], type="array", interactive=False, wrap=True, elem_classes=["rj-readout"])
                log = gr.Textbox(label="日志摘要", value="暂无日志。", lines=6, max_lines=12, interactive=False, elem_classes=["rj-readout"])
            with gr.Column(visible=False) as workshop_page:
                workshop_local, workshop_search, workshop_outputs = render_workshop_page(state, voice_library)
            timer = gr.Timer(1)
            timer.tick(refresh_progress,
                       [progress_snapshot, state["submitting"], state["tts_submitting"], state["notice"]],
                       [progress, progress_snapshot], queue=False, show_progress="hidden")
            detail_inputs = [state["active_task"], state["selected_dataset"], state["submitting"], state["notice"], task_picker]
            detail_outputs = [status, stages, log, audio_submit, voice_submit]
            # Never write to the picker during polling: doing so closes its open menu.
            timer.tick(refresh_status, detail_inputs, detail_outputs, queue=False, show_progress="hidden")
            timer.tick(submission_availability, state["tts_submitting"], tts_refs["submit"], queue=False, show_progress="hidden")
            task_picker.input(refresh_status, detail_inputs, detail_outputs, queue=False, show_progress="hidden")
            refresh_tasks.click(refresh_task_picker, task_picker, task_picker, queue=False, show_progress="hidden")

    render_help()

    pages = [audio_page, voice_page, tts_page, result_page, task_page, workshop_page]
    navigation = [audio_button, voice_button, tts_button, result_button, task_button, workshop_button]
    workshop_button.click(lambda value: gr.update(choices=voice_choices(), value=value),
                          state["selected_voice"], workshop_local, queue=False, show_progress="hidden")
    workshop_button.click(refresh_workshop, workshop_search, workshop_outputs, concurrency_id="workshop-transfer")
    tts_refs["event"].then(show_synthesis_result, state["current_result"],
                           [results, result_audio, result_message] + pages + navigation)
    reuse_button.click(reuse_to_tts, results,
        [state["selected_voice"], tts_voices, tts_refs["text"], tts_refs["emotions"],
         tts_refs["speed"], tts_refs["interval"], result_message] + pages + navigation)
    for index, button in enumerate(navigation):
        button.click(lambda page_index=index: _switch_page(page_index), outputs=pages + navigation, queue=False, show_progress="hidden")
    voice_button.click(lambda selected: gr.update(choices=dataset_choices(), value=selected), state["selected_dataset"], voice_datasets, queue=False, show_progress="hidden")
    voice_button.click(lambda revision: revision + 1, voice_library, voice_library, queue=False, show_progress="hidden")
    audio_button.click(lambda selected, current: gr.skip() if selected == current else gr.update(choices=dataset_choices(), value=selected),
                       [state["selected_dataset"], audio_datasets], audio_datasets, queue=False, show_progress="hidden")
    state["selected_voice"].change(lambda value: (gr.update(choices=voice_choices(), value=value), gr.update(choices=voice_choices(), value=value)),
                                   state["selected_voice"], [voices, tts_voices], queue=False, show_progress="hidden")
    tts_button.click(lambda value: gr.update(choices=voice_choices(), value=value), state["selected_voice"], tts_voices, queue=False, show_progress="hidden")
    result_button.click(refresh_results, state["current_result"],
                        [results, result_audio, result_message], queue=False, show_progress="hidden")
    result_button.click(lambda: "", outputs=state["result_search"], queue=False, show_progress="hidden")
    tts_refs["event"].then(lambda: "", outputs=state["result_search"])
    task_button.click(refresh_task_picker, task_picker, task_picker, queue=False, show_progress="hidden")



