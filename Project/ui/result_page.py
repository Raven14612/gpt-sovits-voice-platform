from __future__ import annotations

import gradio as gr


def render_result_page() -> None:
    gr.Markdown("## 合成结果管理")
    gr.Audio(label="当前结果")
    gr.Markdown("还没有生成记录。成功合成后可在这里播放、下载、复用或删除。")

