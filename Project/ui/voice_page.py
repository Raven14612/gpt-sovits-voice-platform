from __future__ import annotations

import gradio as gr


def render_voice_page() -> None:
    gr.Markdown("## 音色训练与仓库")
    gr.Markdown("选择已经校对的数据集，后台将按固定步骤提取特征并训练 GPT、SoVITS 权重。")
    gr.Dropdown(label="待训练数据集", choices=[], interactive=False)
    gr.Markdown("训练阶段：validating → feature_text → feature_hubert → feature_semantic → train_sovits → train_gpt → packaging")
    gr.Button("生成音色", variant="primary", interactive=False)
    gr.Markdown("当前状态：还没有可训练的数据集；训练未成功前不会显示音色档案。")
    gr.Markdown("### 我的音色")
    gr.Markdown("保存成功的音色会显示在这里；目前为空。")
