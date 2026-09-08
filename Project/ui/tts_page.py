from __future__ import annotations

import gradio as gr
from services import voice_service
from ui.voice_page import voice_choices


def reference_choices(voice_id):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    emotions = [ref.emotion for ref in voice.references] if voice else []
    return gr.update(choices=emotions, value=emotions[0] if emotions else None, interactive=bool(emotions))


def render_tts_page(state):
    gr.Markdown("## 文本生成语音")
    voices = gr.Dropdown(label="选择音色", choices=voice_choices(), value=None, interactive=True)
    gr.Textbox(label="要生成的文字", lines=6, max_lines=10, placeholder="先保存一个可用音色")
    emotions = gr.Radio(label="情绪", choices=[], interactive=False)
    with gr.Accordion("高级设置", open=False):
        gr.Slider(label="语速", minimum=0.5, maximum=2.0, value=1.0, step=0.05)
        gr.Slider(label="句间停顿（秒）", minimum=0.0, maximum=2.0, value=0.3, step=0.1)
    gr.Button("合成语音", variant="primary", interactive=False)
    gr.Textbox(label="合成状态", value="NOT_IMPLEMENTED：项目合成服务尚未接入。", interactive=False)
    voices.input(lambda value: value, voices, state["selected_voice"], queue=False, show_progress="hidden")
    voices.change(reference_choices, voices, emotions, queue=False, show_progress="hidden")
    return voices
