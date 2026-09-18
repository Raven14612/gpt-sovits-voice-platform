"""Gallery-ready images and labels; no data-URI paths passed to Gradio."""
import hashlib
import base64
import io
from html import escape

from PIL import Image, ImageDraw


def placeholder_cover(record):
    digest = hashlib.sha256((record.get("id", "") + record.get("display_name", "")).encode()).digest()
    palette = ("#87443a", "#67829e", "#6e8b5e", "#b08d4f", "#7c638f")
    image = Image.new("RGB", (640, 400), "#f4ecdf")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 624, 384), 16, fill=palette[digest[0] % len(palette)])
    for i in range(19):
        height = 25 + digest[i] % 110
        x = 98 + i * 24
        draw.rounded_rectangle((x, 190-height, x+10, 190+height), 5, fill="#f4ecdf")
    draw.text((34, 352), "VOICE / " + digest.hex()[:6].upper(), fill="#f4ecdf")
    return image


def cover_html(record, client):
    image = client.cover_image(record) or placeholder_cover(record)
    output = io.BytesIO()
    image.save(output, format="WEBP", quality=85)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f'<img src="data:image/webp;base64,{encoded}" alt="{escape(record["display_name"], quote=True)}的封面" loading="lazy">'


def installed_voice(record, profiles):
    source_id = record.get('local_voice_id')
    source = next((voice for voice in profiles if source_id and getattr(voice, 'voice_id', None) == source_id
                   and voice.status in ('verified', 'deleted')), None)
    if source:
        return source
    return next((voice for voice in profiles if voice.origin_type == "workshop"
                 and voice.package_hash == record["package_sha256"]
                 and voice.status in ("verified", "deleted")), None)


def card_caption(record, installed):
    state = "未安装" if installed is None else "已安装" if installed.status == "verified" else "未安装 · 在回收站"
    if installed is not None and installed.origin_type != 'workshop' and installed.status == 'verified':
        state = '已安装 · 本地原音色'
    name, author = escape(record["display_name"]), escape(record["author"])
    return (f'<span class="workshop-install-badge">{state}</span>'
            f'<strong class="workshop-card-name">{name}</strong>'
            f'<span class="workshop-card-author">{author} · {record["package_bytes"] / 1024**2:.1f} MiB</span>')


def details_html(record, installed):
    from datetime import datetime
    uploaded = record['created_at']
    try:
        uploaded = datetime.fromisoformat(uploaded.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except ValueError:
        pass
    status = '已安装' if installed and installed.status == 'verified' else '未安装'
    if installed and installed.status == 'deleted':
        status += '（可从回收站恢复）'
    pairs = [('音色', record['display_name']), ('作者', record['author']), ('作者简介', record['description']),
             ('许可', record['license_name']), ('上传时间', uploaded), ('本地安装状态', status)]
    return '<dl class="workshop-detail-list">' + ''.join(
        f'<div><dt>{label}</dt><dd>{escape(value)}</dd></div>' for label, value in pairs) + '</dl>'
