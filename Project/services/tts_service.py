from models.schemas import AppError


def synthesize(*_args, **_kwargs):
    raise AppError("NOT_IMPLEMENTED", "语音合成尚未接入，不能返回假音频。", stage="synthesis")

