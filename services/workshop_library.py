"""Reversible availability changes for an installed package or its recorded upload source."""
from models.schemas import AppError
from services import voice_service
from services.storage_lock import metadata_lock
from services.workshop_presentation import installed_voice


def change_installation(record, deleted):
    with metadata_lock():
        voice = installed_voice(record, voice_service.list_voices(voice_service.VOICE_INDEX))
        if voice is None:
            raise AppError("WORKSHOP_NOT_INSTALLED", "此音色包尚未安装到本地。")
        voice_service.set_voice_deleted(voice.voice_id, deleted, voice_service.VOICE_INDEX)
        return voice.voice_id
