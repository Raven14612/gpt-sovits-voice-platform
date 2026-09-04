from models.schemas import AppError


def train_voice(*_args, **_kwargs):
    raise AppError("NOT_IMPLEMENTED", "音色训练尚未接入，不能创建假权重。", stage="training")

