from __future__ import annotations

import gradio as gr
from uuid import uuid4

from models.schemas import AppError
from services import (dataset_service, feature_service, task_service,
                      training_preparation_service, voice_service)
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
    def shown(path):
        return dataset_service.relative_path(path)
    return voice.voice_id, (f"{voice.display_name}\n状态：{voice.status}\nGPT：{shown(voice.gpt_weight)}\n"
                            f"SoVITS：{shown(voice.sovits_weight)}\n参考情绪：" + ", ".join(ref.emotion for ref in voice.references))


def submit_training(dataset_id, voice_id, display_name):
    task_id = "train-" + uuid4().hex
    plan = None
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
        plan = training_preparation_service.prepare_training(dataset.dataset_id, voice_id)
        params = training_preparation_service.training_parameters(
            plan, dataset, display_name.strip(), task_id
        )
        task = voice_service.train_voice(dataset, voice_id, params)
        training_preparation_service.finish_training_plan(plan, task)
        message = "训练与权重归档完成。" if task.status.value == "succeeded" else f"训练失败：{task.message}"
        yield task.task_id, False, message
    except (AppError, OSError) as exc:
        if plan is not None:
            training_preparation_service.fail_training_plan(plan, task_id, error_text(exc))
        yield None, False, error_text(exc)
    except Exception as exc:
        if plan is not None:
            training_preparation_service.fail_training_plan(plan, task_id, error_text(exc))
        yield task_id if task_service.get_task(task_id) else None, False, error_text(exc)


def submit_features(dataset_id):
    task_id = "features-" + uuid4().hex
    yield task_id, True, "正在提交特征提取。"
    try:
        task = feature_service.extract_features(dataset_id, task_id=task_id)
        yield task.task_id, False, ""
    except Exception as exc:
        yield None, False, error_text(exc)


def feature_button_state(dataset_id, submitting):
    record = dataset_service.get_dataset(dataset_id) if dataset_id else None
    return gr.update(interactive=bool(record and record.status == "reviewed"
                                     and not submitting and not task_service.is_gpu_busy()))


def render_voice_page(state):
    gr.Markdown("## 音色训练与仓库")
    datasets = gr.Dropdown(label="待训练数据集", choices=dataset_choices(), value=None, interactive=True)
    features = gr.Button("提取特征（不训练）", interactive=False)
    feature_info = gr.Textbox(label="特征状态", value="尚未提取特征。请先保存文本校对。", interactive=False)
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
    datasets.change(feature_service.feature_status, datasets, feature_info)
    features.click(submit_features, datasets,
                   [state["active_task"], state["submitting"], state["notice"]],
                   concurrency_id="model-submit", show_progress="hidden").then(
        feature_service.feature_status, datasets, feature_info)
    feature_timer = gr.Timer(1)
    feature_timer.tick(feature_button_state, [datasets, state["submitting"]], features,
                       queue=False, show_progress="hidden")
    voices.input(lambda value: value, voices, state["selected_voice"], queue=False, show_progress="hidden")
    voices.change(lambda value: voice_details(value)[1], voices, detail, queue=False, show_progress="hidden")
    refresh.click(lambda selected: (gr.update(choices=dataset_choices(), value=selected), voice_rows(), gr.update(choices=voice_choices())),
                  state["selected_dataset"], [datasets, library, voices])
    submit.click(submit_training, [state["selected_dataset"], voice_id, name],
                 [state["active_task"], state["submitting"], state["notice"]], concurrency_id="model-submit").then(
                     voice_rows, outputs=library)
    return datasets, submit, voices
