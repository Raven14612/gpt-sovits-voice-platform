from __future__ import annotations

import gradio as gr

from services.engine_service import probe_engine
from ui.audio_page import render_audio_page
from ui.result_page import render_result_page
from ui.tts_page import render_tts_page
from ui.voice_page import render_voice_page


def _status_markdown() -> str:
    status = probe_engine()
    symbol = "🟢" if status.available else "🟡"
    gpu = f"\n\nGPU：{status.gpu_name}" if status.gpu_name else ""
    return f"### 环境状态\n\n{symbol} {status.message}{gpu}"


def _switch_page(index: int):
    return tuple(gr.update(visible=position == index) for position in range(4))


def render_root_layout() -> None:
    gr.State(value=None)  # selected_dataset
    gr.State(value=None)  # selected_slice
    gr.State(value=None)  # selected_voice
    gr.State(value=None)  # active_task
    gr.State(value=None)  # current_result

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
                render_audio_page()
            with gr.Column(visible=False) as voice_page:
                render_voice_page()
            with gr.Column(visible=False) as tts_page:
                render_tts_page()
            with gr.Column(visible=False) as result_page:
                render_result_page()

    pages = [audio_page, voice_page, tts_page, result_page]
    for index, button in enumerate([audio_button, voice_button, tts_button, result_button]):
        button.click(lambda page_index=index: _switch_page(page_index), outputs=pages)
