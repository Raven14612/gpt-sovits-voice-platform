from __future__ import annotations
import gradio as gr
from models.schemas import AppError
from services import history_service, voice_service
from ui.task_status import error_text
from ui.voice_labels import dataset_names, source_name

def result_choices(query=""):
    query = (query or "").strip()
    try:
        choices = []
        for item in history_service.list_history():
            snapshot = item.get("source_snapshot", {})
            name = snapshot.get("voice_name") or item["voice_id"]
            source = snapshot.get("dataset_name") or "来源未记录"
            text = " ".join(item["text"].split())
            title = item.get("display_name") or text
            if query and query.casefold() not in " ".join([title, text, name, source, item.get("notes", "")]).casefold():
                continue
            excerpt = title[:40] + ("…" if len(title) > 40 else "")
            choices.append((f"{name}［{source}］ · {excerpt} · {item['result_id'][-8:]}", item["result_id"]))
        return choices
    except AppError:
        return []

def search_results(query, selected_result):
    query = (query or "").strip()
    choices = result_choices(query)
    if selected_result not in {value for _, value in choices}:
        selected_result = choices[-1][1] if choices else None
    if not query:
        summary = ""
    elif choices:
        summary = f"找到 {len(choices)} 条成品，已显示匹配结果；可在下方生成记录中切换。"
    else:
        summary = "未找到匹配的成品，请更换关键词或清空搜索。"
    return gr.update(choices=choices, value=selected_result), summary

def select_result(result_id):
    try:
        output = history_service.get_result_output(result_id)
        return result_id if output else None, output, "" if output else "当前没有生成记录。"
    except AppError as exc: return None, None, error_text(exc)

def refresh_results(result_id):
    choices=result_choices()
    if not result_id and choices:
        result_id=choices[-1][1]
    selected,output,message=select_result(result_id)
    return gr.update(choices=choices,value=selected),output,message

def delete_result(result_id):
    if not result_id: return gr.update(choices=result_choices(),value=None),None,"请选择要删除的结果。"
    try:
        history_service.delete_history(result_id)
        return gr.update(choices=result_choices(),value=None),None,"结果已删除。"
    except AppError as exc: return gr.update(choices=result_choices(),value=result_id),None,error_text(exc)

def reuse_result(result_id):
    try:
        record=history_service.reuse_history(result_id)
        return record.get("voice_id",""),record.get("text",""),record.get("emotion","neutral"),record.get("speed_factor",1.0),record.get("fragment_interval",0.3),"已回填音色、文本、情绪与参数。"
    except AppError as exc: return "","","neutral",1.0,0.3,error_text(exc)


def result_details(result_id):
    try:
        item = history_service.get_history(result_id) if result_id else None
        if not item:
            return "", "", "", None
        snapshot = item.get("source_snapshot", {})
        details = (f"生成音色：{snapshot.get('voice_name', item['voice_id'])}\n"
                   f"来源数据集：{snapshot.get('dataset_name', '来源未记录')}\n"
                   f"生成时间：{item.get('created_at', '')}\n"
                   f"合成文本：{item['text']}\n情绪：{item.get('emotion', 'neutral')}")
        return item.get("display_name") or item["text"][:80], item.get("notes", ""), details, None
    except AppError as exc:
        return "", "", error_text(exc), None


def save_result_details(result_id, title, notes, query):
    try:
        history_service.edit_result(result_id, title, notes)
        choices = result_choices(query)
        # Keep the edited result visible even if its old search term no longer matches.
        if result_id not in {v for _, v in choices}:
            choices = result_choices()
        return gr.update(choices=choices, value=result_id), "成品名称与备注已保存。"
    except AppError as exc:
        return gr.skip(), error_text(exc)


def prepare_download(result_id):
    try:
        return history_service.download_result(result_id), "中文文件已准备好，点击下载。"
    except (AppError, OSError) as exc:
        return None, error_text(exc)

def render_result_page(state):
    gr.Markdown("## 成品语音工作台")
    gr.Markdown("成品独立保存。删除来源音色组后，仍可检索、试听、改名、下载和删除。")
    query = gr.Textbox(label="搜索成品", placeholder="名称、文本、音色、数据集或备注")
    search_summary = gr.Markdown("")
    state["result_search"] = query
    results=gr.Dropdown(label="生成记录 · 音色［来源数据集］",choices=result_choices(),value=None,interactive=True)
    audio=gr.Audio(label="当前结果",interactive=False,show_download_button=True)
    message=gr.Textbox(label="结果状态",value="当前没有生成记录。",interactive=False, elem_classes=["rj-readout"])
    title = gr.Textbox(label="成品名称（支持中文）", max_length=80)
    notes = gr.Textbox(label="备注", lines=2, max_length=2000)
    details = gr.Textbox(label="生成资料", lines=5, interactive=False, elem_classes=["rj-readout"])
    save = gr.Button("保存名称与备注", elem_id="hint-result-save")
    with gr.Row():
        download = gr.Button("准备中文文件下载", elem_id="hint-result-download")
        download_file = gr.File(label="下载成品", interactive=False)
    with gr.Row():
        delete=gr.Button("删除结果",variant="stop", elem_id="hint-result-delete")
        reuse=gr.Button("复用参数", elem_id="hint-result-reuse")
    results.change(select_result,results,[state["current_result"],audio,message])
    results.change(result_details, results, [title, notes, details, download_file])
    query.change(search_results, [query, results], [results, search_summary],
                 queue=False, trigger_mode="always_last", show_progress="hidden")
    save.click(save_result_details, [results, title, notes, query], [results, message]).then(
        lambda: None, outputs=download_file)
    download.click(prepare_download, results, [download_file, message])
    delete.click(delete_result,results,[results,audio,message]).then(
        lambda: None, outputs=state["current_result"], queue=False)
    return results,audio,message,reuse


