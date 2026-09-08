from __future__ import annotations

import gradio as gr

from models.schemas import AppError
from services import audio_service, dataset_service
from ui.task_status import error_text


def dataset_choices():
    return [(f"{record.display_name} ({record.status})", record.dataset_id)
            for record in dataset_service.list_datasets()]


def select_dataset(dataset_id):
    if not dataset_id:
        return None, "", [], None, "当前没有数据集。"
    try:
        record = dataset_service.get_dataset(dataset_id)
        if record is None:
            raise AppError("DATASET_MISSING", "数据集已不存在，请刷新列表。")
        rows = dataset_service.load_corrections(dataset_id)
        return dataset_id, str(record.source_path), rows, None, f"{record.display_name} · {record.status}"
    except AppError as exc:
        return dataset_id, "", [], None, error_text(exc)


def upload_audio(path, name):
    try:
        record = dataset_service.import_audio(path, name)
        return gr.update(choices=dataset_choices(), value=record.dataset_id), "音频已保存。"
    except (AppError, OSError) as exc:
        return gr.update(), error_text(exc)


def load_transcript(dataset_id, path):
    try:
        dataset_service.import_transcript(dataset_id, path)
        return dataset_service.load_corrections(dataset_id), None, "识别文本已导入，待人工校对。"
    except (AppError, OSError) as exc:
        return gr.update(), None, error_text(exc)


def save_table(dataset_id, rows):
    try:
        dataset_service.save_corrections(dataset_id, rows)
        return "校对文本和情绪标签已保存。"
    except (AppError, OSError) as exc:
        return error_text(exc)


def select_slice(rows, event: gr.SelectData):
    index = event.index[0]
    if not rows or index >= len(rows):
        return None, "", "", "neutral"
    return index, rows[index][0], rows[index][1], rows[index][2]


def update_slice(rows, selected, text, emotion):
    if selected is None or selected >= len(rows):
        return gr.update(), "请先选择切片。"
    updated = [list(row) for row in rows]
    updated[selected] = [updated[selected][0], text, emotion]
    return updated, "切片已更新，尚未保存。"


def submit_audio(dataset_id, start, end):
    try:
        record = dataset_service.get_dataset(dataset_id)
        if record is None:
            raise AppError("DATASET_MISSING", "请先导入或选择数据集。")
        if start is None or start < 0 or (end is not None and end <= start):
            raise AppError("INVALID_AUDIO", "保留终点必须大于起点；留空表示音频结尾。")
        task = audio_service.process_audio(record, {"start": start, "end": end})
        return task.task_id, "任务已提交。"
    except (AppError, OSError) as exc:
        return gr.skip(), error_text(exc)


def render_audio_page(state):
    gr.Markdown("## 音频数据处理")
    with gr.Row():
        datasets = gr.Dropdown(label="当前数据集", choices=dataset_choices(), value=None, interactive=True)
        refresh = gr.Button("刷新数据集", size="sm", scale=0)
    with gr.Accordion("导入音频", open=True):
        audio = gr.File(label="原始音频 (PCM WAV)", file_types=[".wav"], type="filepath", elem_id="audio-upload")
        preview = gr.Audio(label="上传音频试听", interactive=False)
        name = gr.Textbox(label="数据集名称", max_length=80)
        upload = gr.Button("保存音频", variant="primary")
    source = gr.Textbox(label="已保存音频路径", interactive=False)
    with gr.Row():
        start = gr.Number(label="保留起点（秒）", minimum=0, value=0)
        end = gr.Number(label="保留终点（秒）", minimum=0, value=1, interactive=False)
    to_end = gr.Checkbox(label="保留到音频结尾", value=True)
    submit = gr.Button("切分并识别", variant="primary", interactive=False)
    message = gr.Textbox(label="数据集状态", value="当前没有数据集。", interactive=False)
    with gr.Accordion("导入已有识别文本", open=False):
        transcript = gr.File(label="识别文本 (.list)", file_types=[".list", ".txt"], type="filepath", elem_id="transcript-upload")
        import_list = gr.Button("导入识别文本")
    table = gr.Dataframe(
        headers=["切片", "识别文本", "情绪标签"],
        datatype=["str", "str", "str"], type="array", value=[],
        label="识别与人工校对", interactive=False,
        column_widths=["35%", "45%", "20%"], wrap=True,
    )
    selected_path = gr.Textbox(label="选中切片", interactive=False)
    text = gr.Textbox(label="校对文本", lines=3)
    emotion = gr.Radio(label="人工情绪标签", choices=["neutral", "happy", "sad"], value="neutral")
    with gr.Row():
        apply = gr.Button("更新切片")
        save = gr.Button("保存校对", variant="primary")
    outputs = [state["selected_dataset"], source, table, state["selected_slice"], message]
    audio.change(lambda path: path, audio, preview)
    datasets.change(select_dataset, datasets, outputs).then(
        lambda: ("", "", "neutral"), outputs=[selected_path, text, emotion])
    refresh.click(lambda selected: gr.update(choices=dataset_choices(), value=selected if selected in dict((v, k) for k, v in dataset_choices()) else None),
                  state["selected_dataset"], datasets)
    upload.click(upload_audio, [audio, name], [datasets, message])
    import_list.click(load_transcript, [state["selected_dataset"], transcript], [table, state["selected_slice"], message]).then(
        lambda: ("", "", "neutral"), outputs=[selected_path, text, emotion])
    table.select(select_slice, table, [state["selected_slice"], selected_path, text, emotion])
    apply.click(update_slice, [table, state["selected_slice"], text, emotion], [table, message])
    save.click(save_table, [state["selected_dataset"], table], message)
    to_end.change(lambda value: gr.update(interactive=not value), to_end, end)
    submit.click(lambda dataset_id, start, end, to_end: submit_audio(dataset_id, start, None if to_end else end),
                 [state["selected_dataset"], start, end, to_end], [state["active_task"], state["notice"]])
    return datasets, submit
