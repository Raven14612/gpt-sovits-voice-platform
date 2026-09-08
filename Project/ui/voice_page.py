from __future__ import annotations

import gradio as gr
from uuid import uuid4

from models.schemas import AppError
from services import dataset_service, task_service, voice_service
from ui.audio_page import dataset_choices
from ui.task_status import error_text


def voice_choices():
    return [(item.display_name, item.voice_id) for item in voice_service.list_voices() if item.status == "verified"]


def voice_rows():
    return [[item.display_name, item.voice_id, item.status, item.dataset_id]
            for item in voice_service.list_voices() if item.status == "verified"]


def voice_details(voice_id):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    if voice is None:
        return None, "尚未选择音色。"
    return voice.voice_id, (f"{voice.display_name}\n状态：{voice.status}\nGPT：{voice.gpt_weight or ''}\n"
                            f"SoVITS：{voice.sovits_weight or ''}\n参考情绪：" + ", ".join(ref.emotion for ref in voice.references))


def submit_training(dataset_id, voice_id, display_name):
    task_id = "train-" + uuid4().hex
    yield gr.skip(), True, "正在提交训练。"
    try:
        if task_service.is_gpu_busy():
            raise AppError("GPU_BUSY", "已有任务正在运行。")
        dataset = dataset_service.get_dataset(dataset_id)
        if dataset is None:
            raise AppError("DATASET_MISSING", "请先选择数据集。")
        if dataset.status != "reviewed":
            raise AppError("DATASET_NOT_READY", "请先保存数据集的文本校对和情绪标签。")
        if not display_name or not display_name.strip() or len(display_name.strip()) > 80:
            raise AppError("INVALID_VOICE_NAME", "请输入 1 到 80 个字符的音色名称。")
        yield task_id, True, "正在提交训练。"
        task = voice_service.train_voice(dataset, voice_id, {"task_id": task_id, "display_name": display_name.strip()})
        yield task.task_id, False, ""
    except (AppError, OSError) as exc:
        yield None, False, error_text(exc)
    except Exception as exc:
        yield task_id if task_service.get_task(task_id) else None, False, error_text(exc)


def render_voice_page(state):
    gr.Markdown("## 音色训练与仓库")
    datasets = gr.Dropdown(label="待训练数据集", choices=dataset_choices(), value=None, interactive=True)
    with gr.Row():
        voice_id = gr.Textbox(label="音色 ID", placeholder="例如 citlali-new")
        name = gr.Textbox(label="音色名称", max_length=80)
    submit = gr.Button("生成音色", variant="primary", interactive=False)
    gr.Markdown("### 我的音色")
    library = gr.Dataframe(headers=["名称", "ID", "状态", "数据集"],
                           value=voice_rows(), type="array", interactive=False, wrap=True)
    voices = gr.Dropdown(label="已保存音色", choices=voice_choices(), value=None, interactive=True)
    detail = gr.Textbox(label="音色档案", value="尚未选择音色。", lines=5, interactive=False)
    refresh = gr.Button("刷新音色与数据集")
    datasets.change(lambda value: value, datasets, state["selected_dataset"])
    voices.input(lambda value: value, voices, state["selected_voice"], queue=False, show_progress="hidden")
    voices.change(lambda value: voice_details(value)[1], voices, detail, queue=False, show_progress="hidden")
    refresh.click(lambda selected: (gr.update(choices=dataset_choices(), value=selected), voice_rows(), gr.update(choices=voice_choices())),
                  state["selected_dataset"], [datasets, library, voices])
    submit.click(submit_training, [state["selected_dataset"], voice_id, name],
                 [state["active_task"], state["submitting"], state["notice"]], concurrency_id="model-submit").then(
                     voice_rows, outputs=library)
    return datasets, submit, voices
