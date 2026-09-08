from __future__ import annotations

from pathlib import Path

import gradio as gr

from ui.layout import render_root_layout

PROJECT_ROOT = Path(__file__).resolve().parent
CSS_PATH = PROJECT_ROOT / "assets" / "theme.css"


def load_css() -> str:
    if not CSS_PATH.exists():
        return ""
    return CSS_PATH.read_text(encoding="utf-8")


def build_app() -> gr.Blocks:
    theme = gr.themes.Default(primary_hue="teal", secondary_hue="blue", neutral_hue="gray",
                              font=["Microsoft YaHei", "Arial", "sans-serif"])
    with gr.Blocks(title="轻量级音色克隆", css=load_css(), theme=theme) as demo:
        render_root_layout()
    demo.queue(default_concurrency_limit=1)
    return demo


if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1")
