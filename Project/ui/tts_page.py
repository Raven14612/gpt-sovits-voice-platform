from __future__ import annotations

import gradio as gr


def render_tts_page() -> None:
    gr.Markdown("## 文本生成语音")
    gr.Dropdown(label="选择音色", choices=[], interactive=False)
    gr.Textbox(label="要生成的文字", lines=6, max_lines=10, placeholder="先保存一个可用音色")
    gr.Radio(label="情绪", choices=["中性", "开心", "悲伤"], value="中性", interactive=False)
    with gr.Accordion("高级设置", open=False):
        gr.Slider(label="语速", minimum=0.5, maximum=2.0, value=1.0, step=0.05)
        gr.Slider(label="句间停顿（秒）", minimum=0.0, maximum=2.0, value=0.3, step=0.1)
    gr.Button("合成语音", variant="primary", interactive=False)
    gr.Markdown("当前状态：没有可用音色；模型任务将保持单任务串行。")

