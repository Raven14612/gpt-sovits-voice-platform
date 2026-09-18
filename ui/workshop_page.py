from __future__ import annotations

from pathlib import Path
import logging
from functools import partial
from uuid import uuid4

import gradio as gr

from models.schemas import AppError
from services import voice_package_service as packages
from services.workshop_client import WorkshopClient, load_config
from services.workshop_presentation import cover_html, card_caption, installed_voice, details_html
from services import voice_service, workshop_library
from services.asset_service import checked
from services.project_paths import PROJECT_ROOT
from ui.task_status import error_text
from ui.voice_page import voice_choices
from workshop_server.schemas import LICENSES


def connection_info():
    try:
        return load_config()["base_url"]
    except AppError:
        return "工坊配置无效，请检查 config/workshop.local.json"


def test_connection():
    try:
        WorkshopClient().health()
        return "已连接工坊，API v1。"
    except AppError as exc:
        return error_text(exc)


def current_installation(row):
    return installed_voice(row, voice_service.list_voices(voice_service.VOICE_INDEX))


def request_card(workshop_id, action):
    return {'id': workshop_id, 'action': action, 'request_id': uuid4().hex}


def open_card(workshop_id, action, records):
    row = next((row for row in records if row['id'] == workshop_id), None)
    if row is None:
        return (gr.skip(),) * 10
    installed = current_installation(row)
    available = bool(installed and installed.status == 'verified')
    # Stale card actions must not offer an already completed operation.
    if (action == 'install' and available) or (action == 'uninstall' and not available):
        action = 'details'
    restore = action == 'install' and installed is not None
    message = ''
    if action == 'install':
        message = '此模型仍在回收站，确认后恢复使用，无需重新下载。' if restore else '确认来源与许可后，将下载并安装此模型。'
    elif action == 'uninstall':
        message = '卸载后移入本地回收站，可随时恢复。保留模型文件、训练材料和已生成语音，不影响远程发布。'
    return (workshop_id, action, gr.update(visible=True), details_html(row, installed),
            gr.update(visible=action == 'details' and row.get('can_edit_cover') is True, open=False),
            gr.update(value=False, visible=action == 'install' and not restore),
            gr.update(value='确认卸载' if action == 'uninstall' else '恢复安装' if restore else '确认安装',
                      visible=action != 'details', interactive=True),
            gr.update(value=message, visible=bool(message)), None, '')


def run_card_action(workshop_id, action, records, confirmed, revision, selected_voice):
    # Outputs: library revision, selected local voice, upload choices, details,
    # dialog feedback, action button, consent, grid feedback.
    row = next((row for row in records if row['id'] == workshop_id), None)
    package = None
    try:
        if row is None or action not in ('install', 'uninstall'):
            raise AppError('WORKSHOP_SELECTION_REQUIRED', '操作已失效，请重新打开卡片。')
        installed = current_installation(row)
        if action == 'install' and installed and installed.status == 'verified':
            raise AppError('ALREADY_INSTALLED', '此模型已经安装，无需重复安装。')
        if action == 'uninstall' and (not installed or installed.status != 'verified'):
            raise AppError('WORKSHOP_NOT_INSTALLED', '此模型当前未安装，请刷新卡片。')
        if action == 'install' and installed is None and confirmed is not True:
            raise AppError('INSTALL_CONFIRM_REQUIRED', '请先确认音色来源、许可及网络模型风险。')
        message = '正在卸载模型……' if action == 'uninstall' else '正在恢复模型……' if installed else '正在下载并校验音色包……'
        yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.update(value=message, visible=True),
               gr.update(interactive=False), gr.skip(), gr.update(value=message, visible=True))
        if action == 'uninstall' or installed is not None:
            voice_id = workshop_library.change_installation(row, action == 'uninstall')
            selected = None if action == 'uninstall' and selected_voice == voice_id else selected_voice
            if action == 'install':
                selected = voice_id
            message = '已卸载模型，可点击「安装模型」恢复。' if action == 'uninstall' else '模型已恢复安装。'
        else:
            pending, message, _, _ = download_selected(workshop_id, records, None)
            if pending is None:
                raise AppError('WORKSHOP_DOWNLOAD_FAILED', message)
            package = pending['path']
            yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.update(value='下载完成，正在安全校验并安装……', visible=True),
                   gr.update(interactive=False), gr.skip(), gr.update(value='下载完成，正在安装……', visible=True))
            if packages.inspect_voice_package(package)['package_sha256'] != pending['hash']:
                raise AppError('PACKAGE_CHANGED', '下载包已变化，请重试。')
            voice = packages.install_voice_package(package, origin_workshop_id=workshop_id)
            selected = voice.voice_id
            message = '模型安装成功，可前往「文本生成语音」使用。'
        yield (revision + 1, selected, gr.update(choices=voice_choices(), value=selected),
               details_html(row, current_installation(row)), gr.update(value=message, visible=True),
               gr.update(visible=False, interactive=True), gr.update(value=False, visible=False),
               gr.update(value=message, visible=True))
    except (AppError, OSError) as exc:
        message = error_text(exc) if isinstance(exc, AppError) else '文件处理失败，请检查文件占用和磁盘空间后重试。'
        yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.update(value=message, visible=True),
               gr.update(interactive=True), gr.skip(), gr.update(value=message, visible=True))
    except Exception as exc:
        logging.getLogger(__name__).error('Workshop card action failed: %s', type(exc).__name__)
        yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.update(value='操作失败，请重试。', visible=True),
               gr.update(interactive=True), gr.skip(), gr.update(value='操作失败，请重试。', visible=True))
    finally:
        try:
            cleanup_package(package, area='tmp/workshop-downloads')
        except (AppError, OSError):
            logging.getLogger(__name__).warning('Workshop temporary package cleanup deferred')


def save_cover(workshop_id, records, path, token):
    if not path or not any(row["id"] == workshop_id for row in records):
        return gr.skip(), "请先选择音色并上传封面图片。"
    if not any(row['id'] == workshop_id and row.get('can_edit_cover') is True for row in records):
        return gr.skip(), '仅上传者可以修改此音色的封面。'
    try:
        client = WorkshopClient()
        digest = client.set_cover(workshop_id, path, token)
        updated = [dict(row, cover_sha256=digest) if row["id"] == workshop_id else row for row in records]
        return updated, "封面已保存到工坊，刷新或重启后仍会显示。"
    except AppError as exc:
        return gr.skip(), error_text(exc)


def open_card_dialog(request, records):
    result = open_card(request['id'], request['action'], records)
    row = next((r for r in records if r['id'] == request['id']), {})
    return (*result, gr.update(visible=request['action'] == 'details' and row.get('can_withdraw') is True, open=False), False, '')


def withdraw_selected(workshop_id, records, confirmed):
    row = next((r for r in records if r['id'] == workshop_id), {})
    if row.get('can_withdraw') is not True:
        return gr.skip(), gr.skip(), gr.skip(), '仅上传者可以下架此音色。', gr.skip()
    if confirmed is not True:
        return gr.skip(), gr.skip(), gr.skip(), '请先确认下架影响。', gr.skip()
    try:
        WorkshopClient().withdraw_voice(workshop_id)
        return ([r for r in records if r['id'] != workshop_id], None, gr.update(visible=False), '',
                gr.update(value='音色已从工坊下架，停止新下载；所有已安装的本地副本保留。', visible=True))
    except AppError as exc:
        return gr.skip(), gr.skip(), gr.skip(), error_text(exc), gr.skip()


def refresh_workshop(query):
    try:
        client = WorkshopClient()
        records = client.list_voices(query or "", limit=100)
        message = f"已连接 · 显示 {len(records)} 个音色。" if records else "已连接 · 暂无匹配音色。"
        return records, None, message
    except AppError as exc:
        return [], None, error_text(exc)


def cleanup_package(value, *, area):
    if value:
        path = checked(Path(value), PROJECT_ROOT, areas=(area,))
        if path.suffix == ".rvoice":
            path.unlink(missing_ok=True)


def upload_selected(voice_id, author, description, license_name, rights, token):
    package = None
    uploaded = None
    message = "上传未完成。"
    try:
        if not voice_id:
            raise AppError("VOICE_SELECTION_REQUIRED", "请先选择要上传的本地音色。")
        # Render feedback before the CPU checkpoint check and large file copying.
        yield "正在校验并打包音色，包含 CPU 权重安全预检；请等待，不要重复点击。", gr.update(interactive=False), None
        package = packages.export_voice_package(voice_id, author, description, license_name, rights)
        yield (f"音色包已生成（{Path(package).stat().st_size / 1024**2:.1f} MiB），正在上传并等待服务端校验。",
               gr.update(interactive=False), None)
        result = WorkshopClient().upload_voice(package, token, local_voice_id=voice_id)
        uploaded = result["id"]
        message = f'上传成功。工坊条目 ID：{uploaded}'
    except (AppError, OSError) as exc:
        message = error_text(exc) if isinstance(exc, AppError) else "上传文件处理失败，请检查文件权限和磁盘空间后重试。"
    except Exception as exc:
        # Do not reflect credentials, remote responses or local paths in errors.
        logging.getLogger(__name__).error("Workshop upload failed: %s", type(exc).__name__)
        message = "上传发生异常，请重试；若持续失败，请查看平台错误日志。"
    finally:
        try:
            cleanup_package(package, area="tmp/voice-packages")
        except (AppError, OSError):
            message += " 临时音色包暂时无法清理，请释放文件占用后重试清理。"
    yield message, gr.update(interactive=True), uploaded


def refresh_after_upload(uploaded):
    if not uploaded:
        return (gr.skip(),) * 4
    # Clear a previous search so the newly uploaded voice is immediately visible.
    return ("",) + refresh_workshop("")


def download_selected(workshop_id, records, pending):
    package = None
    try:
        if pending:
            cleanup_package(pending.get("path"), area="tmp/workshop-downloads")
        selected = next((r for r in records if r["id"] == workshop_id), None)
        if selected is None:
            raise AppError("WORKSHOP_SELECTION_REQUIRED", "请先刷新并选择工坊音色。")
        package = WorkshopClient().download_voice(workshop_id, expected_size=selected["package_bytes"],
                                                   expected_sha256=selected["package_sha256"])
        info = packages.inspect_voice_package(package)
        voice = info["manifest"]["voice"]
        details = (f'下载完成，尚未安装。\n音色：{voice["display_name"]}\n作者：{voice["author"]}\n'
                   f'简介：{voice["description"]}\n许可：{info["manifest"]["license"]["name"]}\n'
                   "来源：创意工坊。网络模型存在风险；请确认来源和许可后再安装。")
        return {"path": str(package), "id": workshop_id, "hash": info["package_sha256"]}, details, False, gr.update(interactive=True)
    except (AppError, OSError) as exc:
        cleanup_package(package, area="tmp/workshop-downloads")
        return None, error_text(exc) if isinstance(exc, AppError) else "下载文件处理失败，请重试。", False, gr.update(interactive=False)


def render_workshop_page(state, voice_library):
    gr.Markdown("## 音色创意工坊")
    records = gr.State([])
    selected = gr.State(None)
    mode = gr.State('details')
    card_request = gr.State(None)
    with gr.Row(elem_classes=["workshop-status-bar"]):
        gr.Textbox(label="服务地址", value=connection_info(), interactive=False, scale=3, min_width=180)
        connect = gr.Button("测试连接", elem_id="hint-workshop-connect", scale=1, min_width=110)
        status = gr.Textbox(label="工坊状态", value="等待连接", interactive=False, lines=1, max_lines=3, scale=3, min_width=180,
                            elem_classes=["rj-readout"])
    with gr.Column(elem_id="workshop-browser", elem_classes=["workshop-browser"]):
        with gr.Row(elem_classes=["workshop-search-row"]):
            search = gr.Textbox(label="搜索名称或作者", value="", placeholder="输入名称或作者", max_length=200, scale=5, min_width=100)
            refresh = gr.Button("刷新列表", elem_id="hint-workshop-refresh", scale=1, min_width=110)
        with gr.Column(elem_id="workshop-grid"):
            @gr.render(inputs=[records, voice_library], concurrency_id="workshop-transfer", show_progress="hidden")
            def render_cards(rows, revision):
                with gr.Column(elem_classes=["workshop-card-grid"]):
                    if not rows:
                        gr.HTML('<div class="workshop-grid-empty"><strong>暂无音色</strong>'
                                '<span>尝试其他搜索词，或在下方上传本地音色。</span></div>', padding=False)
                        return
                    client = WorkshopClient()
                    profiles = voice_service.list_voices(voice_service.VOICE_INDEX)
                    for row in rows:
                        wid = row['id']
                        installed = installed_voice(row, profiles)
                        available = bool(installed and installed.status == 'verified')
                        with gr.Column(min_width=0, elem_classes=['workshop-tile'], key=('tile', wid)):
                            gr.HTML(cover_html(row, client), padding=False, elem_classes=['workshop-tile-cover'],
                                    key=('image', wid), preserved_by_key=[])
                            with gr.Column(min_width=0, elem_classes=['workshop-card-overlay']):
                                gr.HTML(card_caption(row, installed), padding=False,
                                        elem_classes=['workshop-card-caption'], key=('caption', wid), preserved_by_key=[])
                                card_detail = gr.Button('查看详情', size='sm', min_width=0)
                                card_action = gr.Button('卸载模型' if available else '安装模型',
                                                        variant='secondary' if available else 'primary', size='sm', min_width=0)
                                card_detail.click(partial(request_card, wid, 'details'), outputs=card_request,
                                                  concurrency_id='workshop-transfer', show_progress='hidden')
                                card_action.click(partial(request_card, wid, 'uninstall' if available else 'install'), outputs=card_request,
                                                  concurrency_id='workshop-transfer', show_progress='hidden')
        card_status = gr.Textbox(label='卡片操作结果', visible=False, interactive=False, elem_classes=['rj-readout'])
    with gr.Column(visible=False, elem_id='workshop-modal') as modal:
        with gr.Column(elem_id='workshop-dialog-panel', min_width=0):
            with gr.Row(elem_classes=['workshop-dialog-header']):
                gr.HTML('<h3 id="workshop-dialog-title">音色详情</h3>', padding=False)
                close = gr.Button('关闭', size='sm', min_width=60, scale=0, elem_id='workshop-dialog-close')
            details = gr.HTML('', padding=False, elem_id='workshop-dialog-details')
            with gr.Accordion('设置封面', visible=False, open=False, elem_id='workshop-cover-editor') as cover_editor:
                cover = gr.File(label='封面图片 · PNG / JPEG / WebP，最大 4 MiB', file_types=['.png', '.jpg', '.jpeg', '.webp'], type='filepath')
                cover_token = gr.State('')
                cover_save = gr.Button('保存封面', elem_id='hint-workshop-cover')
                cover_status = gr.Textbox(label='封面状态', interactive=False, elem_classes=['rj-readout'])
            with gr.Accordion('下架我上传的音色', visible=False, open=False, elem_id='workshop-withdraw-editor') as withdrawal:
                gr.Markdown('下架后从公开列表隐藏并停止新下载。已安装的本地音色保持可用，服务器保留存档。')
                withdraw_confirm = gr.Checkbox(label='我确认从工坊下架此音色，保留各客户端的本地副本', value=False)
                withdraw_button = gr.Button('确认下架', elem_id='workshop-withdraw-action')
                withdraw_status = gr.Textbox(label='下架状态', interactive=False)
            operation_status = gr.Textbox(label='操作说明', visible=False, interactive=False, lines=2, max_lines=5, elem_classes=['rj-readout'])
            confirm = gr.Checkbox(label='我已核对来源和许可，并了解网络模型存在风险，同意安装', value=False, visible=False)
            action_button = gr.Button('确认安装', variant='primary', visible=False, elem_id='workshop-confirm-action')
    with gr.Accordion('上传本地音色', open=False, elem_id='workshop-uploader'):
        uploaded = gr.State(None)
        local = gr.Dropdown(label='本地可用音色', choices=voice_choices(), interactive=True)
        author = gr.Textbox(label='作者', max_length=80)
        description = gr.Textbox(label='简介', max_length=2000, lines=3)
        license_name = gr.Dropdown(label='许可', choices=list(LICENSES), value=LICENSES[1])
        rights = gr.Checkbox(label='我确认拥有分享该音色、权重及参考音频的权利', value=False)
        token = gr.Textbox(label='远程工坊上传令牌（本地自动启动的工坊无需填写）', type='password', value='')
        upload = gr.Button('上传选中音色', elem_id='hint-workshop-upload')
        upload_status = gr.Textbox(label='上传状态', value='填写信息后点击上传；进度与结果将显示在这里。',
                                   interactive=False, lines=3, max_lines=6, elem_id='workshop-upload-status', elem_classes=['rj-readout'])
    dialog_outputs = [selected, mode, modal, details, cover_editor, confirm, action_button, operation_status, cover, cover_status]
    card_request.change(open_card_dialog,
                        [card_request, records], dialog_outputs + [withdrawal, withdraw_confirm, withdraw_status],
                        concurrency_id='workshop-transfer', show_progress='hidden')
    withdraw_button.click(withdraw_selected, [selected, records, withdraw_confirm],
                          [records, selected, modal, withdraw_status, card_status], concurrency_id='workshop-transfer',
                          show_progress='full', trigger_mode='once')
    connect.click(test_connection, outputs=status)
    close.click(lambda: gr.update(visible=False), outputs=modal, queue=False, show_progress='hidden')
    refresh_outputs = [records, selected, status]
    gr.on(triggers=[refresh.click, search.submit], fn=refresh_workshop, inputs=search, outputs=refresh_outputs, concurrency_id='workshop-transfer')
    cover_save.click(save_cover, [selected, records, cover, cover_token], [records, cover_status], concurrency_id='workshop-transfer')
    action_button.click(run_card_action, [selected, mode, records, confirm, voice_library, state['selected_voice']],
                        [voice_library, state['selected_voice'], local, details, operation_status, action_button, confirm, card_status],
                        concurrency_id='workshop-transfer', show_progress='hidden', trigger_mode='once')
    upload.click(lambda: ('已收到上传请求，正在等待工坊操作完成……', gr.update(interactive=False), None),
                 outputs=[upload_status, upload, uploaded], queue=False, show_progress='hidden').then(
        upload_selected, [local, author, description, license_name, rights, token],
        [upload_status, upload, uploaded], concurrency_id='workshop-transfer', show_progress='hidden'
    ).then(refresh_after_upload, uploaded, [search] + refresh_outputs, concurrency_id='workshop-transfer', show_progress='hidden')
    return local, search, refresh_outputs
