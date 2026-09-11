from __future__ import annotations

import gradio as gr
from models.schemas import AppError
from services import history_service
from ui.task_status import error_text


def result_choices():
    return [(item.get("text", item["result_id"])[:60], item["result_id"])
            for item in history_service.list_history()
            if item.get("result_id") and item.get("status") == "succeeded"]


def select_result(result_id):
    try:
        output = history_service.get_result_output(result_id)
        return result_id if output else None, output, "" if output else "当前没有生成记录。"
    except AppError as exc:
        return None, None, error_text(exc)


def refresh_results(result_id):
    choices = result_choices()
    selected, output, message = select_result(result_id)
    return gr.update(choices=choices, value=selected), output, message


def render_result_page(state):
    gr.Markdown("## 合成结果管理")
    results = gr.Dropdown(label="生成记录", choices=result_choices(), value=None, interactive=True)
    audio = gr.Audio(label="当前结果", interactive=False)
    message = gr.Textbox(label="结果状态", value="当前没有生成记录。", interactive=False)
    results.change(select_result, results, [state["current_result"], audio, message])
    return results, audio, message
