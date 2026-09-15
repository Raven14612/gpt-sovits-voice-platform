from __future__ import annotations

from pathlib import Path

import gradio as gr

from ui.layout import render_root_layout
from ui.theme import build_theme
from services.task_service import recover_tasks
from services.history_service import recover_history
from models.schemas import AppError
import json

PROJECT_ROOT = Path(__file__).resolve().parent
CSS_PATH = PROJECT_ROOT / "assets" / "theme.css"
TOKENS_PATH = PROJECT_ROOT / "assets" / "retro-tokens.css"


def load_css() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (TOKENS_PATH, CSS_PATH))


def build_app() -> gr.Blocks:
    hints = json.loads((PROJECT_ROOT / "assets/button-hints.json").read_text(encoding="utf-8"))
    hint_js = (PROJECT_ROOT / "assets/button-hints.js").read_text(encoding="utf-8").replace(
        "__BUTTON_HINTS__", json.dumps(hints, ensure_ascii=True))
    with gr.Blocks(title="小渡鸦的语音合成平台哟", css=load_css(), theme=build_theme(),
                   fill_width=True, elem_classes=["rj-theme"], js=hint_js) as demo:
        render_root_layout()
    demo.queue(default_concurrency_limit=1)
    return demo


def main(*, port=7860):
    from services.process_lifetime import install_process_lifetime_job
    install_process_lifetime_job()
    try:
        from services.asset_service import recover_deletions, migrate_ownership
        from services.history_service import backfill_snapshots
        recover_deletions()
        backfill_snapshots()
        migrate_ownership()
        recover_tasks()
        report = recover_history()
        recovery_log = PROJECT_ROOT / "data/logs/recovery.json"
        recovery_log.parent.mkdir(parents=True, exist_ok=True)
        recovery_log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except (AppError, OSError) as exc:
        raise RuntimeError(f"仓库恢复未完成，启动已停止：{exc}") from exc
    # Let Gradio open the local UI once the server is ready. The port is
    # forwarded from launch.py, so custom --port starts open the right URL.
    from services.ui_instance import register, unregister
    demo = build_app()
    app_id = demo.config["app_id"]
    register(app_id, port)
    try:
        demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=True)
    finally:
        from adapters.inference_runtime import runtime
        try:
            runtime.close()
        finally:
            unregister(app_id, port)


if __name__ == "__main__":
    main()
