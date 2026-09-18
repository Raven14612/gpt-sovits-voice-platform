from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import gradio as gr
from models.schemas import AppError
from services import history_service, tts_service, voice_service
from ui.task_status import error_text
from ui.voice_page import voice_choices
from services.task_service import is_gpu_busy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "data" / "outputs"


def reference_choices(voice_id):
    voice = voice_service.get_voice(voice_id) if voice_id else None
    emotions = [ref.emotion for ref in voice.references] if voice else []
    return gr.update(choices=emotions, value=emotions[0] if emotions else None, interactive=bool(emotions))


def submit_synthesis(voice_id, text, emotion, speed_factor, fragment_interval):
    if not voice_id:
        return None, None, "VOICE_WEIGHTS_MISSING：请先选择音色。"
    if not str(text or "").strip():
        return None, None, "REFERENCE_MISSING：请输入要生成的文字。"
    result_id = f"tts-{uuid4().hex}"
    output = OUTPUT_ROOT / f"{result_id}.wav"
    try:
        generated = tts_service.synthesize(
            voice_id=voice_id,
            target_text=str(text).strip(),
            emotion=emotion or "neutral",
            speed_factor=float(speed_factor),
            fragment_interval=float(fragment_interval),
            output_path=output,
        )
        return result_id, str(generated), "合成成功，结果已保存。"
    except (AppError, OSError, ValueError) as exc:
        return None, None, error_text(exc)


def synthesis_updates(voice_id, text, emotion, speed, interval):
    yield None, None, "等待提交；正在检查输入与 GPU 状态。", gr.update(interactive=False), True
    result, output, message = submit_synthesis(voice_id, text, emotion, speed, interval)
    yield result, output, message, gr.update(interactive=not is_gpu_busy()), False


def submission_availability(submitting):
    return gr.update(interactive=not submitting and not is_gpu_busy())


def render_tts_page(state):
    gr.Markdown("## 文本生成语音")
    voices = gr.Dropdown(label="选择音色", choices=voice_choices(), value=None, interactive=True)
    text = gr.Textbox(label="要生成的文字", lines=6, max_lines=10, placeholder="输入要生成的中文文本")
    emotions = gr.Radio(label="情绪", choices=[], interactive=False)
    with gr.Accordion("高级设置", open=False):
        speed = gr.Slider(label="语速", minimum=0.5, maximum=2.0, value=1.0, step=0.05)
        interval = gr.Slider(label="句间停顿（秒，暂不支持调整）", minimum=0.0, maximum=2.0, value=0.3, step=0.1, interactive=False)
        gr.Markdown(tts_service.capabilities()["reason"])
    submit = gr.Button("合成语音", variant="primary", interactive=True)
    status = gr.Textbox(label="合成状态", value="请选择音色并输入文本。", interactive=False, elem_classes=["rj-readout"])
    audio = gr.Audio(label="合成结果", interactive=False, show_download_button=True)
    voices.input(lambda value: value, voices, state["selected_voice"], queue=False, show_progress="hidden")
    voices.input(reference_choices, voices, emotions, queue=False, show_progress="hidden")
    state["selected_voice"].change(reference_choices, state["selected_voice"], emotions, queue=False, show_progress="hidden")
    event = submit.click(
        synthesis_updates,
        [voices, text, emotions, speed, interval],
        [state["current_result"], audio, status, submit, state["tts_submitting"]],
        show_progress="hidden",
        trigger_mode="once",
        concurrency_id="synthesis",
        concurrency_limit=1,
    )
    return {"voices": voices, "text": text, "emotions": emotions, "speed": speed, "interval": interval,
            "submit": submit, "event": event}

