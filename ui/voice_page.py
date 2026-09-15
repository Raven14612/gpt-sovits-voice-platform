from __future__ import annotations

import gradio as gr
from html import escape
from uuid import uuid4

from models.schemas import AppError
from services import (dataset_service, feature_service, task_service,
                      training_preparation_service, voice_service)
from ui.audio_page import dataset_choices
from ui.task_status import error_text
from ui.voice_labels import dataset_names, source_name


def voice_choices():
    return [(item.display_name, item.voice_id) for item in voice_service.list_voices() if item.status == "verified"]


def voice_rows():
    return [[item.display_name, item.voice_id, item.status, item.dataset_id]
            for item in voice_service.list_voices() if item.status == "verified"]


def deleted_voice_choices():
    return [(item.display_name, item.voice_id) for item in voice_service.list_voices() if item.status == "deleted"]


def refresh_library_pickers(selected_voice, deleted_voice):
    choices = voice_choices()
    deleted = deleted_voice_choices()
    selected = selected_voice if selected_voice in {value for _, value in choices} else None
    removed = deleted_voice if deleted_voice in {value for _, value in deleted} else None
    return gr.update(choices=choices, value=selected), gr.update(choices=deleted, value=removed), selected


def _preview_voice(voice_id, status):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    enabled = voice is not None and voice.status == status
    text = voice_row_html(voice, dataset_names()) if enabled else "请从上方下拉框选择音色。"
    return text, gr.update(interactive=enabled), gr.update(interactive=enabled)


def preview_available_voice(voice_id):
    return _preview_voice(voice_id, "verified")


def preview_deleted_voice(voice_id):
    return _preview_voice(voice_id, "deleted")


def show_voice_archive(voice_id):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    if voice is None:
        return gr.skip(), gr.update(open=True), "音色已不存在或尚未选择，请刷新列表后重试。", "无法读取音色档案。"
    return (voice.voice_id if voice.status == "verified" else gr.skip(),
            gr.update(open=True), _voice_detail_text(voice), f"已打开「{voice.display_name}」的音色档案。")


def voice_row_html(voice, sources):
    emotions = {"neutral": "普通", "happy": "高兴", "sad": "悲伤"}
    tags = " / ".join(emotions.get(ref.emotion, ref.emotion) for ref in voice.references) or "尚无参考情绪"
    status = "已删除" if voice.status == "deleted" else "可用"
    return (f'<div class="voice-summary"><div class="voice-summary-title">'
            f'<strong>{escape(voice.display_name)}</strong><span class="voice-status">{status}</span></div>'
            f'<p>来源数据集：{escape(source_name(voice.dataset_id, sources))}</p>'
            f'<p class="voice-metadata">ID：{escape(voice.voice_id)} · 情绪：{escape(tags)}'
            f' · 创建：{voice.created_at.astimezone().strftime("%Y-%m-%d %H:%M")}</p></div>')


def refresh_library(revision, selected_voice):
    choices = voice_choices()
    selected = selected_voice if selected_voice in {value for _, value in choices} else None
    return revision + 1, gr.update(choices=choices, value=selected), selected


def change_library_voice(voice_id, deleted, revision, selected_voice):
    try:
        if not voice_id:
            raise AppError("VOICE_MISSING", "请先选择音色。")
        voice_service.set_voice_deleted(voice_id, deleted)
        updated = refresh_library(revision, selected_voice)
        message = "音色已移出可用列表，可从「已删除音色」下拉框选择并恢复。" if deleted else "音色已恢复，可从「显示音色」下拉框选择。"
        return (*updated, message, gr.update(open=False), "请选择音色并点击「查看档案」。")
    except (AppError, OSError) as exc:
        return gr.skip(), gr.skip(), gr.skip(), error_text(exc), gr.skip(), gr.skip()


def request_voice_purge(voice_id):
    try:
        if not voice_id:
            raise AppError("VOICE_MISSING", "请先选择已删除音色。")
        pending = voice_service.prepare_voice_purge(voice_id)
        text = (f"确认彻底删除「{pending['display_name']}」（ID：{voice_id}）？\n"
                f"将清理 {pending['files']} 个文件，约 {pending['bytes'] / 1024 / 1024:.1f} MB。\n"
                "包括平台原音频副本、切片、全部标注、特征、训练工程及两个权重；不可恢复。已合成成品保留。")
        return pending, gr.update(visible=True), text
    except (AppError, OSError) as exc:
        return None, gr.update(visible=True), error_text(exc)


def confirm_voice_purge(pending, current_voice, revision, selected_voice):
    try:
        if not pending or pending["voice_id"] != current_voice:
            raise AppError("VOICE_CHANGED", "未确认目标或选择已变化，请重新点击「彻底删除」。")
        voice_service.purge_voice(current_voice, pending["fingerprint"])
        return (*refresh_library(revision, selected_voice), "音色文件组及关联材料已彻底删除；已合成成品保留。",
                gr.update(open=False), "请选择音色并点击「查看档案」。", None, gr.update(visible=False))
    except (AppError, OSError) as exc:
        return (gr.skip(), gr.skip(), gr.skip(), error_text(exc), gr.skip(), gr.skip(), None, gr.update(visible=False))


def voice_details(voice_id):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    if voice is None:
        return None, "尚未选择音色。"
    return voice.voice_id, _voice_detail_text(voice)


def _voice_detail_text(voice):
    def shown(path):
        return dataset_service.relative_path(path) if path else "未记录"
    status = {"verified": "可用", "deleted": "已删除", "draft": "未完成"}.get(voice.status, voice.status)
    return (f"{voice.display_name}\nID：{voice.voice_id}\n状态：{status}\n"
                            f"来源数据集：{source_name(voice.dataset_id, dataset_names())}\nGPT：{shown(voice.gpt_weight)}\n"
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
            raise AppError("DATASET_NOT_READY", "请先在「音频数据处理」点击「确认标注并用于训练」。")
        if not display_name or not display_name.strip() or len(display_name.strip()) > 80:
            raise AppError("INVALID_VOICE_NAME", "请输入 1 到 80 个字符的音色名称。")
        voice_id = voice_id.strip() if voice_id and voice_id.strip() else "voice-" + uuid4().hex
        yield task_id, True, "正在准备独立训练材料。"
        plan = training_preparation_service.prepare_training(dataset.dataset_id, voice_id)
        from services.asset_service import read_json
        dataset = dataset_service.get_dataset(read_json(plan, {})["dataset_id"])
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


def training_guidance(dataset_id, submitting):
    if submitting or task_service.is_gpu_busy():
        return "当前有任务正在提交或运行，请等待完成。进度与失败原因可在左侧「任务与日志」查看。"
    if not dataset_id:
        return "请先在上方选择已确认标注的数据集；如还未导入，请前往「音频数据处理」。"
    record = dataset_service.get_dataset(dataset_id)
    if record is None:
        return "所选数据集已不存在，请刷新数据集列表后重新选择。"
    if record.status != "reviewed":
        return "请前往「音频数据处理」点击「确认标注并用于训练」；可直接采用识别结果，需要修改时再展开校对面板。"
    if not record.feature_manifest:
        return "校对已保存。请先完成第 1 步「准备训练数据（提取特征）」，再填写音色组名称，进行第 2 步训练。"
    return "已记录提取的特征。请填写音色组名称，再开始训练；启动前会检查特征是否完整、是否对应当前校对版本。"


def render_voice_page(state):
    gr.Markdown("## 音色训练与仓库")
    gr.Markdown("选择已确认标注的数据集 → 准备训练数据 → 训练并保存音色。完成后可在「文本生成语音」中使用。")
    datasets = gr.Dropdown(label="待训练数据集", choices=dataset_choices(), value=None, interactive=True)
    guidance = gr.Markdown("请先在上方选择已确认标注的数据集；如还未导入，请前往「音频数据处理」。", elem_classes=["rj-readout", "rj-readout-prose"])
    gr.Markdown("### 第 1 步：准备训练数据\n\n将校对后的音频与文本转换为训练所需的特征，完成后再进行模型训练。")
    features = gr.Button("准备训练数据（提取特征）", interactive=False)
    feature_info = gr.Textbox(label="训练数据准备状态", value="请先选择数据集。", interactive=False, elem_classes=["rj-readout"])
    gr.Markdown("### 第 2 步：训练并保存音色\n\n完成第 1 步后，填写音色组名称。训练将生成 GPT / SoVITS 权重，并将音色保存到下方「我的音色」。")
    with gr.Row():
        voice_id = gr.Textbox(label="音色 ID", value="", visible=False)
        name = gr.Textbox(label="音色文件组名称（支持中文）", max_length=80)
    submit = gr.Button("开始训练并保存音色", variant="primary", interactive=False)
    gr.Markdown("任务提交后，可在左侧「任务与日志」查看进度与失败原因。")
    library = gr.State(0)
    with gr.Column(elem_id="voice-library", min_width=0):
        gr.Markdown("### 我的音色")
        gr.Markdown("移入回收站后，可在下方「已删除音色」中恢复或彻底删除。彻底删除会清理音色组及全部关联训练材料，已合成成品独立保留。")
        voices = gr.Dropdown(label="显示音色", choices=voice_choices(), value=None,
                             interactive=True, elem_id="available-voice-picker")
        with gr.Row(elem_classes=["voice-library-row"]):
            active_summary = gr.HTML("请选择要显示的音色。", elem_classes=["rj-readout", "rj-readout-prose"])
            with gr.Column(scale=0, min_width=120, elem_classes=["voice-row-actions"]):
                inspect = gr.Button("查看档案", size="sm", interactive=False)
                remove = gr.Button("移入回收站", size="sm", interactive=False)
        deleted_voices = gr.Dropdown(label="已删除音色", choices=deleted_voice_choices(), value=None,
                                     interactive=True, elem_id="deleted-voice-picker")
        with gr.Row(elem_classes=["voice-library-row"]):
            deleted_summary = gr.HTML("暂无选中的已删除音色。", elem_classes=["rj-readout", "rj-readout-prose"])
            with gr.Column(scale=0, min_width=120, elem_classes=["voice-row-actions"]):
                restore = gr.Button("恢复已选项目", size="sm", interactive=False)
                purge = gr.Button("彻底删除", variant="stop", size="sm", interactive=False)
        pending_purge = gr.State(None)
        with gr.Column(visible=False) as purge_confirmation:
            purge_text = gr.Textbox(label="彻底删除确认", lines=3, interactive=False, elem_classes=["rj-readout", "rj-readout-alert"])
            with gr.Row():
                confirm_purge = gr.Button("确认彻底删除", variant="stop")
                cancel_purge = gr.Button("取消")
        library_message = gr.Textbox(label="音色操作提示", value="请从上方下拉框选择音色。", interactive=False, elem_classes=["rj-readout"])
        with gr.Accordion("选中音色档案", open=False, elem_id="voice-archive") as archive:
            detail = gr.Textbox(label="音色档案", value="请选择音色并点击「查看档案」。", lines=6, interactive=False, elem_classes=["rj-readout"])

    # Each click returns the archive content AND open state directly. It must
    # work even when the same voice is already selected in the shared state.
    archive_outputs = [state["selected_voice"], archive, detail, library_message]
    inspect.click(show_voice_archive, voices, archive_outputs, queue=False, show_progress="hidden")
    voices.change(preview_available_voice, voices, [active_summary, inspect, remove],
                  queue=False, show_progress="hidden")
    deleted_voices.change(preview_deleted_voice, deleted_voices, [deleted_summary, restore, purge],
                          queue=False, show_progress="hidden")
    deleted_voices.change(lambda: (None, gr.update(visible=False)), outputs=[pending_purge, purge_confirmation],
                          queue=False, show_progress="hidden")
    library.change(refresh_library_pickers, [voices, deleted_voices],
                   [voices, deleted_voices, state["selected_voice"]], queue=False, show_progress="hidden")
    mutation_outputs = [library, voices, state["selected_voice"], library_message, archive, detail]
    remove.click(lambda vid, rev, selected: change_library_voice(vid, True, rev, selected),
                 [voices, library, state["selected_voice"]], mutation_outputs, show_progress="hidden")
    restore.click(lambda vid, rev, selected: change_library_voice(vid, False, rev, selected),
                  [deleted_voices, library, state["selected_voice"]], mutation_outputs, show_progress="hidden")
    purge.click(request_voice_purge, deleted_voices, [pending_purge, purge_confirmation, purge_text],
                queue=False, show_progress="hidden")
    def refresh_dataset_after_delete(selected):
        choices = dataset_choices()
        selected = selected if selected in {value for _, value in choices} else None
        return gr.update(choices=choices, value=selected), selected
    confirm_purge.click(confirm_voice_purge, [pending_purge, deleted_voices, library, state["selected_voice"]],
                        mutation_outputs + [pending_purge, purge_confirmation], show_progress="hidden").then(
        refresh_dataset_after_delete, state["selected_dataset"], [datasets, state["selected_dataset"]])
    cancel_purge.click(lambda: (None, gr.update(visible=False)), outputs=[pending_purge, purge_confirmation],
                       queue=False, show_progress="hidden")
    refresh = gr.Button("刷新音色与数据集", elem_id="hint-voice-refresh")
    retry = gr.Button("重试未完成清理", elem_id="hint-voice-retry")
    def retry_cleanup():
        from services.asset_service import recover_deletions
        try:
            recover_deletions()
            return "清理已完成，请刷新音色与数据集。"
        except (AppError, OSError) as exc:
            return error_text(exc)
    retry.click(retry_cleanup, outputs=library_message).then(
        refresh_library, [library, state["selected_voice"]], [library, voices, state["selected_voice"]]).then(
        refresh_dataset_after_delete, state["selected_dataset"], [datasets, state["selected_dataset"]])
    datasets.change(lambda value: value, datasets, state["selected_dataset"])
    datasets.change(feature_service.feature_status, datasets, feature_info)
    datasets.change(training_guidance, [datasets, state["submitting"]], guidance,
                    queue=False, show_progress="hidden")
    features.click(submit_features, datasets,
                   [state["active_task"], state["submitting"], state["notice"]],
                   concurrency_id="model-submit", show_progress="hidden").then(
        feature_service.feature_status, datasets, feature_info)
    feature_timer = gr.Timer(1)
    feature_timer.tick(feature_button_state, [datasets, state["submitting"]], features,
                       queue=False, show_progress="hidden")
    feature_timer.tick(training_guidance, [datasets, state["submitting"]], guidance,
                       queue=False, show_progress="hidden")
    voices.input(lambda value: value, voices, state["selected_voice"], queue=False, show_progress="hidden")
    refresh.click(lambda selected, rev, voice: (gr.update(choices=dataset_choices(), value=selected), *refresh_library(rev, voice)),
                  [state["selected_dataset"], library, state["selected_voice"]],
                  [datasets, library, voices, state["selected_voice"]])
    submit.click(submit_training, [state["selected_dataset"], voice_id, name],
                 [state["active_task"], state["submitting"], state["notice"]], concurrency_id="model-submit", show_progress="hidden").then(
                     refresh_library, [library, state["selected_voice"]],
                     [library, voices, state["selected_voice"]])
    return datasets, submit, voices, library
