from __future__ import annotations

import gradio as gr


def render_audio_page() -> None:
    gr.Markdown("## 音频数据处理")
    gr.Markdown("上传纯人声音频，之后将在这里完成裁剪、切分、识别和人工校对。")
    gr.Audio(label="原始音频", type="filepath")
    with gr.Row():
        gr.Number(label="保留起点（秒）", minimum=0, value=0)
        gr.Number(label="保留终点（秒）", minimum=0)
    gr.Button("切分并识别", variant="primary", interactive=False)
    gr.Dataframe(
        headers=["切片", "识别文本", "情绪标签"],
        datatype=["str", "str", "str"],
        value=[],
        label="识别与人工校对",
        interactive=False,
    )
    gr.Markdown("当前状态：后端尚未接入，因此按钮暂不可用。")

