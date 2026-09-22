"""Local user guide, rendered once with the UI and opened without a server call."""
from html import escape
from pathlib import Path

import gradio as gr
from markdown_it import MarkdownIt

GUIDE_PATH = Path(__file__).resolve().parents[1] / "assets" / "user-guide.md"


def guide_html() -> str:
    parser = MarkdownIt("commonmark", {"html": False})
    tokens = parser.parse(GUIDE_PATH.read_text(encoding="utf-8"))
    links = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            anchor = f"help-section-{len(links) + 1}"
            token.attrSet("id", anchor)
            token.attrSet("tabindex", "-1")
            links.append(f'<a href="#{anchor}">{escape(tokens[index + 1].content)}</a>')
    content = parser.renderer.render(tokens, parser.options, {})
    return f'''<dialog id="project-help-dialog" aria-labelledby="project-help-title">
        <header class="help-header">
            <div><span class="help-eyebrow">使用指南 · 随时查阅</span>
            <h2 id="project-help-title">项目的使用帮助</h2></div>
            <button type="button" id="project-help-close" autofocus>关闭</button>
        </header>
        <div class="help-layout">
            <nav class="help-toc" aria-label="使用说明目录"><strong>阅读目录</strong>{''.join(links)}</nav>
            <article class="help-content" tabindex="0" aria-label="使用说明正文">{content}</article>
        </div>
    </dialog>'''


def render_help() -> None:
    gr.HTML('''<nav aria-label="页脚链接">
        <a href="#project-help-dialog" id="project-help-open" aria-haspopup="dialog">项目的使用帮助</a>
        <span aria-hidden="true">·</span>
        <a href="https://www.gradio.app/" target="_blank" rel="noopener noreferrer">Gradio技术鸣谢</a>
        <span aria-hidden="true">·</span>
        <a href="https://github.com/Raven14612" target="_blank" rel="noopener noreferrer">关于</a>
    </nav>''', elem_id="project-footer", padding=False)
    gr.HTML(guide_html(), elem_id="project-help", padding=False)
