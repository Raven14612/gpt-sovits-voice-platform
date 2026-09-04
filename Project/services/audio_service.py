from models.schemas import AppError


def process_audio(*_args, **_kwargs):
    raise AppError("NOT_IMPLEMENTED", "音频处理尚未接入，当前只完成页面和接口骨架。", stage="audio")

