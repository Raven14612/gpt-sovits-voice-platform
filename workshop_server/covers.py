"""Bounded raster decoding and metadata-free PNG covers."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from workshop_server.storage import PackageError

MAX_COVER_BYTES = 4 * 1024 * 1024


def normalize_cover(data):
    try:
        if not 0 < len(data) <= MAX_COVER_BYTES:
            raise ValueError("size")
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or source.width * source.height > 16_000_000:
                raise ValueError("format or dimensions")
            cover = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (640, 400))
            output = io.BytesIO()
            cover.save(output, format="PNG")
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise PackageError("COVER_INVALID", "请选择不超过 4 MiB、1600 万像素的 PNG、JPEG 或 WebP 封面。") from exc
