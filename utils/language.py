from typing import Optional

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from data.Async_sqlDataBase import data_db as db
from utils.texts import get_text


SUPPORTED_LANGS = {"uz", "ru"}
LANGUAGE_BUTTON_KEYS = (
    "register",
    "login",
    "cancel",
    "back",
    "yes",
    "no",
    "logout",
    "confirm",
    "profile",
    "language",
    "feedback",
    "contacts",
    "china_address",
    "search",
    "by_trek",
    "by_my_code",
    "manage_users",
    "add_user",
    "search_user",
    "upload_db",
    "broadcast",
    "admin_search",
)


def normalize_lang(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip().lower()
    return value if value in SUPPORTED_LANGS else None


def infer_language_from_text(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None

    for lang in ("uz", "ru"):
        for key in LANGUAGE_BUTTON_KEYS:
            if text == get_text(lang, key):
                return lang

    return None


async def resolve_language(
    message: Message,
    state: FSMContext,
    *,
    prefer_message_text: bool = False,
    active_only: bool = False,
    default: str = "uz",
) -> str:
    text_lang = infer_language_from_text(getattr(message, "text", None))
    if prefer_message_text and text_lang:
        return text_lang

    active_user = await db.get_user_by_telegram_id(message.from_user.id, active_only=True)
    active_user_lang = normalize_lang(active_user.get("language") if active_user else None)
    if active_user_lang:
        return active_user_lang

    if not active_only:
        inactive_user = await db.get_user_by_telegram_id(message.from_user.id, active_only=False)
        inactive_user_lang = normalize_lang(inactive_user.get("language") if inactive_user else None)
        if inactive_user_lang:
            return inactive_user_lang

    data = await state.get_data()
    state_lang = normalize_lang(data.get("language"))
    if state_lang:
        return state_lang

    if text_lang:
        return text_lang

    return normalize_lang(default) or "uz"


async def clear_state_keep_language(state: FSMContext, lang: str) -> None:
    await state.clear()
    await state.update_data(language=normalize_lang(lang) or "uz")
