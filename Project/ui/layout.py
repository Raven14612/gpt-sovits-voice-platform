from __future__ import annotations

import gradio as gr

from services.engine_service import probe_engine
from ui.audio_page import render_audio_page
from ui.result_page import render_result_page, result_choices
from ui.tts_page import render_tts_page
from ui.voice_page import render_voice_page, voice_choices
from ui.audio_page import dataset_choices
from ui.task_status import refresh_status


def _status_markdown() -> str:
    status = probe_engine()
    symbol = "🟢" if status.available else "🟡"
    gpu = f"\n\nGPU：{status.gpu_name}" if status.gpu_name else ""
    return f"### 环境状态\n\n{symbol} {status.message}{gpu}"


def _switch_page(index: int):
    return (tuple(gr.update(visible=position == index) for position in range(4))
            + tuple(gr.update(variant="primary" if position == index else "secondary") for position in range(4)))


def render_root_layout() -> None:
    state = {key: gr.State(value=None) for key in (
        "selected_dataset", "selected_slice", "selected_voice", "active_task", "current_result")}
    state["submitting"] = gr.State(False)
    state["notice"] = gr.State("")

    with gr.Row(elem_id="topbar"):
        gr.Markdown("# 轻量级音色克隆")
        gr.Markdown("本地运行 · RTX 50 系主线")

    with gr.Row(elem_id="app-shell"):
        with gr.Column(scale=1, min_width=220, elem_id="sidebar"):
            audio_button = gr.Button("音频数据处理", variant="primary")
            voice_button = gr.Button("音色训练与仓库")
            tts_button = gr.Button("文本生成语音")
            result_button = gr.Button("合成结果管理")
            gr.Markdown(_status_markdown(), elem_id="environment-status")

        with gr.Column(scale=4, elem_id="page-content"):
            with gr.Column(visible=True) as audio_page:
                audio_datasets, audio_submit = render_audio_page(state)
            with gr.Column(visible=False) as voice_page:
                voice_datasets, voice_submit, voices = render_voice_page(state)
            with gr.Column(visible=False) as tts_page:
                tts_voices = render_tts_page(state)
            with gr.Column(visible=False) as result_page:
                results = render_result_page(state)

            with gr.Accordion("任务与日志", open=True):
                task_picker = gr.Dropdown(label="已保存任务", choices=[], interactive=True)
                status = gr.Textbox(label="任务状态", value="当前没有任务。", lines=4, interactive=False)
                stages = gr.Dataframe(headers=["阶段", "退出码", "检查信息", "日志文件"], value=[], type="array", interactive=False, wrap=True)
                log = gr.Textbox(label="日志摘要", value="暂无日志。", lines=6, max_lines=12, interactive=False)
            timer = gr.Timer(1)
            timer.tick(refresh_status, [state["active_task"], state["selected_dataset"], state["submitting"], state["notice"]],
                       [task_picker, status, stages, log, audio_submit, voice_submit], queue=False, show_progress="hidden")
            task_picker.input(lambda task_id: (task_id, ""), task_picker, [state["active_task"], state["notice"]])

    pages = [audio_page, voice_page, tts_page, result_page]
    navigation = [audio_button, voice_button, tts_button, result_button]
    for index, button in enumerate(navigation):
        button.click(lambda page_index=index: _switch_page(page_index), outputs=pages + navigation, queue=False, show_progress="hidden")
    voice_button.click(lambda selected: gr.update(choices=dataset_choices(), value=selected), state["selected_dataset"], voice_datasets, queue=False, show_progress="hidden")
    audio_button.click(lambda selected, current: gr.skip() if selected == current else gr.update(choices=dataset_choices(), value=selected),
                       [state["selected_dataset"], audio_datasets], audio_datasets, queue=False, show_progress="hidden")
    state["selected_voice"].change(lambda value: (gr.update(choices=voice_choices(), value=value), gr.update(choices=voice_choices(), value=value)),
                                   state["selected_voice"], [voices, tts_voices], queue=False, show_progress="hidden")
    tts_button.click(lambda value: gr.update(choices=voice_choices(), value=value), state["selected_voice"], tts_voices, queue=False, show_progress="hidden")
    result_button.click(lambda value: gr.update(choices=result_choices(), value=value), state["current_result"], results, queue=False, show_progress="hidden")
