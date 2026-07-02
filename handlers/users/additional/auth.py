"""
Auth Handlers - Ro'yxatdan o'tish va Login (Optimized)
"""
import os
import logging
from aiogram import F
from loader import dp, bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, FSInputFile, InputMediaPhoto

from data.config import (
    CLIENT_CODE_PREFIX,
    PASSPORT_TEMPLATE,
    PINFL_TEMPLATE,
    PassportType,
    VERIFICATION_GROUP_ID
)
from data.Async_sqlDataBase import data_db as db
from utils.validators import Validators
from utils.texts import get_text
from utils.keyboards import (
    welcome_keyboard,
    main_menu_keyboard,
    cancel_keyboard,
    passport_type_keyboard,
    confirm_keyboard,
    verification_inline_keyboard
)
from utils.formatters import format_phone_display, format_verification_status
from utils.language import clear_state_keep_language, resolve_language
from utils.rate_limiter import login_limiter

from states.AdminStates import RegistrationStates, LoginStates, ProfileCompletionStates


logger = logging.getLogger(__name__)


# Helper: Guruhlarda keyboard yuborilmasligi uchun
def get_is_private(message: Message) -> bool:
    """Check if message is from private chat"""
    return message.chat.type == 'private'


PHONE_VALIDATION_ERROR_KEYS = {
    "Telefon raqam kiritilmadi": "phone_error_empty",
    "Telefon raqam noto'g'ri formatda": "phone_error_invalid_format",
    "Telefon raqam 12 ta raqamdan iborat bo'lishi kerak": "phone_error_invalid_length",
}


def get_phone_validation_error(lang: str, message: str) -> str:
    """Translate validator phone errors without changing validator API."""
    key = PHONE_VALIDATION_ERROR_KEYS.get(message)
    return get_text(lang, key) if key else message


PROFILE_FIELD_ORDER = [
    "fullname",
    "phone",
    "passport_number",
    "birth_date",
    "pinfl",
    "address",
]

PROFILE_FIELD_STATES = {
    "fullname": ProfileCompletionStates.entering_fullname,
    "passport_number": ProfileCompletionStates.entering_passport_number,
    "birth_date": ProfileCompletionStates.entering_birth_date,
    "pinfl": ProfileCompletionStates.entering_pinfl,
    "address": ProfileCompletionStates.entering_address,
}

PROFILE_FIELD_PROMPTS = {
    "fullname": "enter_fullname",
    "passport_number": "enter_passport_number",
    "birth_date": "enter_birth_date",
    "pinfl": "enter_pinfl",
    "address": "enter_address",
}


def is_missing_profile_value(value) -> bool:
    text = str(value or "").strip()
    return not text or text.casefold() in {"none", "nan", "null", "-", "—"}


def normalize_phone_for_compare(phone: str) -> str:
    valid, _, normalized = Validators.validate_phone(str(phone or ""))
    if valid:
        return normalized
    return ""


def build_profile_payload(state_data: dict, existing_user: dict | None = None) -> dict:
    payload = {}
    existing_user = existing_user or {}
    for field in PROFILE_FIELD_ORDER:
        value = state_data.get(field)
        if is_missing_profile_value(value):
            value = existing_user.get(field, "")
        payload[field] = value or ""

    return payload


async def finish_approved_login(message: Message, state: FSMContext, lang: str, user: dict, client_code: str):
    login_limiter.reset(message.from_user.id)
    await state.clear()
    await state.update_data(language=lang, user_id=user['id'])

    try:
        await db.execute(
            'UPDATE users SET language = ? WHERE id = ?',
            (lang, user['id'])
        )
        await db.update_user_id(message.from_user.id, client_code)
        await db.activate_user(message.from_user.id)
    except Exception as e:
        logger.error(f"Error finalizing login: {e}")

    await message.answer(
        get_text(lang, 'login_success', fullname=user['fullname']),
        reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
    )


async def answer_non_approved_login(message: Message, state: FSMContext, lang: str, user: dict, client_code: str):
    await state.clear()
    await state.update_data(language=lang, user_id=user['id'])

    try:
        await db.execute(
            'UPDATE users SET language = ? WHERE id = ?',
            (lang, user['id'])
        )
        await db.update_user_id(message.from_user.id, client_code)
        await db.activate_user(message.from_user.id)
    except Exception as e:
        logger.error(f"Error linking pending/rejected user: {e}")

    status_text = format_verification_status(user['verification_status'], lang)
    if user['verification_status'] == 'rejected':
        status_message = get_text(lang, 'status_rejected', reason=user.get('rejection_reason') or "—")
    else:
        status_message = get_text(lang, 'status_pending')

    await message.answer(
        get_text(
            lang,
            'welcome_registered',
            fullname=user['fullname'],
            client_code=user['client_code'],
            phone=format_phone_display(user['phone']),
            status=status_text,
            status_message=status_message
        ),
        reply_markup=welcome_keyboard(lang, get_is_private(message))
    )


async def start_profile_completion(
    message: Message,
    state: FSMContext,
    lang: str,
    client_code: str,
    existing_user: dict | None,
    provided_fields: dict | None = None,
):
    provided_fields = provided_fields or {}
    existing_missing = db.get_missing_profile_fields(existing_user) if existing_user else PROFILE_FIELD_ORDER
    missing_fields = [
        field for field in PROFILE_FIELD_ORDER
        if field != "phone"
        and field in existing_missing
        and is_missing_profile_value(provided_fields.get(field))
    ]

    completion_data = {
        "language": lang,
        "completion_client_code": existing_user.get("client_code") if existing_user else client_code,
        "completion_user_id": existing_user.get("id") if existing_user else None,
        "completion_is_new": existing_user is None,
        "completion_missing_fields": missing_fields,
    }
    completion_data.update(provided_fields)
    await state.update_data(**completion_data)

    intro_key = "client_code_not_found_complete" if existing_user is None else "client_profile_incomplete"
    await message.answer(
        get_text(
            lang,
            intro_key,
            client_code=completion_data["completion_client_code"]
        ),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )
    await ask_next_profile_completion_field(message, state, lang)


async def ask_next_profile_completion_field(message: Message, state: FSMContext, lang: str):
    data = await state.get_data()
    missing_fields = data.get("completion_missing_fields", [])

    for field in missing_fields:
        if is_missing_profile_value(data.get(field)):
            await state.set_state(PROFILE_FIELD_STATES[field])
            if field == "passport_number":
                await send_passport_template(message, lang)
            elif field == "pinfl" and os.path.exists(PINFL_TEMPLATE):
                try:
                    await message.answer_photo(FSInputFile(PINFL_TEMPLATE), caption="📸 PINFL")
                except Exception as e:
                    logger.warning(f"PINFL template yuborishda xatolik: {e}")

            await message.answer(
                get_text(lang, PROFILE_FIELD_PROMPTS[field]),
                reply_markup=cancel_keyboard(lang, get_is_private(message))
            )
            return

    existing_user = None
    if data.get("completion_user_id"):
        existing_user = await db.get_user_by_id(data["completion_user_id"])
        if not existing_user:
            existing_user = await db.get_user_by_client_code(data["completion_client_code"], active_only=False)

    payload = build_profile_payload(data, existing_user)
    await state.set_state(ProfileCompletionStates.confirming_profile)
    await message.answer(
        get_text(
            lang,
            'confirm_profile_completion',
            client_code=data["completion_client_code"],
            fullname=payload["fullname"],
            phone=format_phone_display(payload["phone"]),
            passport=payload["passport_number"],
            birth_date=payload["birth_date"],
            pinfl=payload["pinfl"],
            address=payload["address"]
        ),
        reply_markup=confirm_keyboard(lang, get_is_private(message))
    )


# ==================== RO'YXATDAN O'TISH ====================

@dp.message(F.text.in_([
    get_text('uz', 'register'),
    get_text('ru', 'register')
]))
async def start_registration(message: Message, state: FSMContext):
    """Ro'yxatdan o'tishni boshlash"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    await state.update_data(language=lang)
    
    await state.set_state(RegistrationStates.entering_fullname)
    await message.answer(
        get_text(lang, 'enter_fullname'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.entering_fullname, F.text)
async def process_fullname(message: Message, state: FSMContext):
    """F.I.O ni qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, formatted = Validators.validate_fullname(message.text)
    
    if not valid:
        await message.answer(f"❌ {msg}\n\n{get_text(lang, 'enter_fullname')}")
        return
    
    await state.update_data(fullname=formatted)
    await state.set_state(RegistrationStates.entering_phone)
    
    await message.answer(
        get_text(lang, 'enter_phone'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.entering_phone, F.text)
async def process_phone(message: Message, state: FSMContext):
    """Telefon raqamini qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, phone = Validators.validate_phone(message.text)
    
    if not valid:
        await message.answer(f"❌ {get_phone_validation_error(lang, msg)}\n\n{get_text(lang, 'enter_phone')}")
        return
    
    await state.update_data(phone=phone)
    await state.set_state(RegistrationStates.selecting_passport_type)
    
    await message.answer(
        get_text(lang, 'select_passport_type'),
        reply_markup=passport_type_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.selecting_passport_type, F.text)
async def process_passport_type(message: Message, state: FSMContext):
    """Pasport turi tanlash"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    if message.text == get_text(lang, 'passport_id_card'):
        await state.update_data(passport_type=PassportType.ID_CARD)
        await state.set_state(RegistrationStates.uploading_passport_front)
        
        await message.answer(
            get_text(lang, 'upload_passport_front'),
            reply_markup=cancel_keyboard(lang, get_is_private(message))
        )
    elif message.text == get_text(lang, 'passport_booklet'):
        await state.update_data(passport_type=PassportType.BOOKLET)
        await state.set_state(RegistrationStates.uploading_passport_booklet)
        
        await message.answer(
            get_text(lang, 'upload_passport_booklet'),
            reply_markup=cancel_keyboard(lang, get_is_private(message))
        )
    else:
        await message.answer(
            get_text(lang, 'invalid_command'),
            reply_markup=passport_type_keyboard(lang, get_is_private(message))
        )


@dp.message(RegistrationStates.uploading_passport_front, F.photo)
async def process_passport_front(message: Message, state: FSMContext):
    """Pasport old tomonini qabul qilish (ID card)"""
    lang = await resolve_language(message, state, active_only=False)

    try:
        # Eng katta rasmni olish
        photo = message.photo[-1]

        # File ID ni saqlash (rasmni yuklamasdan)
        await state.update_data(
            passport_front_file_id=photo.file_id,
            passport_front_file_unique_id=photo.file_unique_id
        )
        await state.set_state(RegistrationStates.uploading_passport_back)

        await message.answer(
            get_text(lang, 'upload_passport_back'),
            reply_markup=cancel_keyboard(lang, get_is_private(message))
        )
    except Exception as e:
        logger.error(f"Pasport old tomoni yuklashda xatolik: {e}", exc_info=True)
        await message.answer(get_text(lang, 'error_photo'))


@dp.message(RegistrationStates.uploading_passport_back, F.photo)
async def process_passport_back(message: Message, state: FSMContext):
    """Pasport orqa tomonini qabul qilish (ID card)"""
    lang = await resolve_language(message, state, active_only=False)

    try:
        photo = message.photo[-1]

        # File ID ni saqlash (rasmni yuklamasdan)
        await state.update_data(
            passport_back_file_id=photo.file_id,
            passport_back_file_unique_id=photo.file_unique_id
        )
        await state.set_state(RegistrationStates.entering_passport_number)

        # Template ni yuborish
        await send_passport_template(message, lang)

        await message.answer(
            get_text(lang, 'enter_passport_number'),
            reply_markup=cancel_keyboard(lang, get_is_private(message))
        )
    except Exception as e:
        logger.error(f"Pasport orqa tomoni yuklashda xatolik: {e}", exc_info=True)
        await message.answer(get_text(lang, 'error_photo'))


@dp.message(RegistrationStates.uploading_passport_booklet, F.photo)
async def process_passport_booklet(message: Message, state: FSMContext):
    """Pasport rasmini qabul qilish (Kitobli)"""
    lang = await resolve_language(message, state, active_only=False)

    try:
        photo = message.photo[-1]

        # File ID ni saqlash (kitobli uchun front va back bir xil)
        await state.update_data(
            passport_front_file_id=photo.file_id,
            passport_back_file_id=photo.file_id,
            passport_front_file_unique_id=photo.file_unique_id,
            passport_back_file_unique_id=photo.file_unique_id
        )
        await state.set_state(RegistrationStates.entering_passport_number)

        # Template ni yuborish
        await send_passport_template(message, lang)

        await message.answer(
            get_text(lang, 'enter_passport_number'),
            reply_markup=cancel_keyboard(lang, get_is_private(message))
        )
    except Exception as e:
        logger.error(f"Pasport (kitobli) yuklashda xatolik: {e}", exc_info=True)
        await message.answer(get_text(lang, 'error_photo'))


async def send_passport_template(message: Message, lang: str):
    """Pasport template rasmni yuborish"""
    if os.path.exists(PASSPORT_TEMPLATE):
        try:
            await message.answer_photo(
                FSInputFile(PASSPORT_TEMPLATE),
                caption="📸 Pasport seriya va raqami SHU YERDA"
            )
        except Exception as e:
            logger.warning(f"Template yuborishda xatolik: {e}")


@dp.message(RegistrationStates.entering_passport_number, F.text)
async def process_passport_number(message: Message, state: FSMContext):
    """Pasport raqamini qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, passport = Validators.validate_passport_number(message.text)
    
    if not valid:
        await message.answer(f"❌ {msg}")
        return
    
    await state.update_data(passport_number=passport)
    await state.set_state(RegistrationStates.entering_birth_date)
    
    await message.answer(
        get_text(lang, 'enter_birth_date'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.entering_birth_date, F.text)
async def process_birth_date(message: Message, state: FSMContext):
    """Tug'ilgan sanani qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, birth_date, warning, _ = Validators.validate_birth_date(message.text)
    
    if not valid:
        await message.answer(f"❌ {msg}")
        return
    
    await state.update_data(
        birth_date=birth_date
    )
    
    # Pasport muddati ogohlantiruvi
    if warning:
        await message.answer(warning)
    
    await state.set_state(RegistrationStates.entering_pinfl)
    
    # PINFL template
    if os.path.exists(PINFL_TEMPLATE):
        try:
            await message.answer_photo(
                FSInputFile(PINFL_TEMPLATE),
                caption="📸 PINFL SHU YERDA"
            )
        except Exception as e:
            logger.warning(f"PINFL template yuborishda xatolik: {e}")
    
    await message.answer(
        get_text(lang, 'enter_pinfl'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.entering_pinfl, F.text)
async def process_pinfl(message: Message, state: FSMContext):
    """PINFL ni qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, pinfl = Validators.validate_pinfl(message.text)
    
    if not valid:
        await message.answer(f"❌ {msg}")
        return
    
    await state.update_data(pinfl=pinfl)
    await state.set_state(RegistrationStates.entering_address)
    
    await message.answer(
        get_text(lang, 'enter_address'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.entering_address, F.text)
async def process_address(message: Message, state: FSMContext):
    """Manzilni qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    valid, msg, address = Validators.validate_address(message.text)
    
    if not valid:
        await message.answer(f"❌ {msg}")
        return
    
    await state.update_data(address=address)
    await state.set_state(RegistrationStates.confirming_registration)
    
    # Ma'lumotlarni ko'rsatish
    data = await state.get_data()
    
    await message.answer(
        get_text(lang, 'confirm_registration',
                fullname=data['fullname'],
                phone=format_phone_display(data['phone']),
                passport=data['passport_number'],
                birth_date=data['birth_date'],
                pinfl=data['pinfl'],
                address=data['address']),
        reply_markup=confirm_keyboard(lang, get_is_private(message))
    )


@dp.message(RegistrationStates.confirming_registration, F.text)
async def confirm_registration(message: Message, state: FSMContext):
    """Ro'yxatdan o'tishni tasdiqlash"""
    import asyncio
    
    data = await state.get_data()
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'confirm'):
        # Foydalanuvchini saqlash
        success, msg = await db.register_user(message.from_user.id, data)

        if success:
            # User ni olish
            user = await db.get_user_by_telegram_id(message.from_user.id)

            # Verification guruhga yuborishni background taskda ishlatish
            asyncio.create_task(send_to_verification_group(user, data))

            await clear_state_keep_language(state, lang)
            await message.answer(
                get_text(lang, 'registration_submitted'),
                reply_markup=main_menu_keyboard(lang, is_private=get_is_private(message))
            )
        else:
            await message.answer(f"❌ Xatolik: {msg}")
    
    elif message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )


async def send_to_verification_group(user: dict, data: dict):
    """Ma'lumotlarni verification guruhga yuborish (rasmlar album ko'rinishida)"""
    try:
        # Matn tayyorlash (optimized formatting)
        text = (
            "🆕 YANGI RO'YXATDAN O'TUVCHI\n\n"
            f"👤 F.I.O: {user['fullname']}\n"
            f"📱 Telefon: {format_phone_display(user['phone'])}\n"
            f"🆔 Pasport: {user['passport_number']}\n"
            f"📅 Tug'ilgan: {user['birth_date']}\n"
            f"🔢 PINFL: {user['pinfl']}\n"
            f"📍 Manzil: {user['address']}\n\n"
            f"🔐 Mijoz kodi: {user['client_code'] or 'Hali yaratilmagan'}\n"
            f"📅 Ro'yxat: {user['registered_at']}"
        )
        
        # Pasport rasmlarini album sifatida yuborish
        media_group = []
        passport_front = data.get('passport_front_file_id')
        passport_back = data.get('passport_back_file_id')
        
        if passport_front:
            # Birinchi rasmga caption qo'shish
            caption = "📸 Pasport" if passport_back == passport_front else "📸 Pasport (OLD)"
            media_group.append(
                InputMediaPhoto(
                    media=passport_front,
                    caption=caption
                )
            )
        
        # Orqa tomoni bor va old tomondan farqli bo'lsa (ID card uchun)
        if passport_back and passport_back != passport_front:
            media_group.append(
                InputMediaPhoto(
                    media=passport_back,
                    caption="📸 Pasport (ORQA)"
                )
            )
        
        # Album yuborish (agar rasmlar mavjud bo'lsa)
        if media_group:
            await bot.send_media_group(
                chat_id=VERIFICATION_GROUP_ID,
                media=media_group
            )
        
        # Ma'lumot va tugmalar bilan xabar yuborish
        msg = await bot.send_message(
            chat_id=VERIFICATION_GROUP_ID,
            text=text,
            reply_markup=verification_inline_keyboard(user['id'], 'uz')
        )
        
        # Verification queue ga qo'shish
        await db.add_to_verification_queue(user['id'], msg.message_id)
        
        logger.info(f"User {user['id']} ({user['fullname']}) verification guruhga yuborildi")
        
    except Exception as e:
        logger.error(f"Verification guruhga yuborishda xatolik (user: {user.get('id', 'unknown')}): {e}", exc_info=True)


# ==================== PROFILNI TO'LDIRISH ====================

@dp.message(ProfileCompletionStates.entering_fullname, F.text)
async def complete_fullname(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    valid, msg, formatted = Validators.validate_fullname(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\n{get_text(lang, 'enter_fullname')}")
        return

    await state.update_data(fullname=formatted)
    await ask_next_profile_completion_field(message, state, lang)


@dp.message(ProfileCompletionStates.entering_passport_number, F.text)
async def complete_passport_number(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    valid, msg, passport = Validators.validate_passport_number(message.text)
    if not valid:
        await message.answer(f"❌ {msg}")
        return

    await state.update_data(passport_number=passport)
    await ask_next_profile_completion_field(message, state, lang)


@dp.message(ProfileCompletionStates.entering_birth_date, F.text)
async def complete_birth_date(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    valid, msg, birth_date, warning, _ = Validators.validate_birth_date(message.text)
    if not valid:
        await message.answer(f"❌ {msg}")
        return

    await state.update_data(birth_date=birth_date)
    if warning:
        await message.answer(warning)
    await ask_next_profile_completion_field(message, state, lang)


@dp.message(ProfileCompletionStates.entering_pinfl, F.text)
async def complete_pinfl(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    valid, msg, pinfl = Validators.validate_pinfl(message.text)
    if not valid:
        await message.answer(f"❌ {msg}")
        return

    await state.update_data(pinfl=pinfl)
    await ask_next_profile_completion_field(message, state, lang)


@dp.message(ProfileCompletionStates.entering_address, F.text)
async def complete_address(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    valid, msg, address = Validators.validate_address(message.text)
    if not valid:
        await message.answer(f"❌ {msg}")
        return

    await state.update_data(address=address)
    await ask_next_profile_completion_field(message, state, lang)


@dp.message(ProfileCompletionStates.confirming_profile, F.text)
async def confirm_profile_completion(message: Message, state: FSMContext):
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    data = await state.get_data()

    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    if message.text != get_text(lang, 'confirm'):
        await message.answer(get_text(lang, 'confirm_or_cancel'))
        return

    existing_user = None
    if data.get("completion_user_id"):
        existing_user = await db.get_user_by_client_code(data["completion_client_code"], active_only=False)

    payload = build_profile_payload(data, existing_user)
    success, msg, user, created, needs_review = await db.complete_client_profile(
        data["completion_client_code"],
        message.from_user.id,
        payload,
        lang
    )

    if not success or not user:
        await message.answer(f"❌ {msg}")
        return

    if needs_review:
        await send_to_verification_group(user, payload)
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'profile_completion_submitted'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return

    await finish_approved_login(message, state, lang, user, user['client_code'])


# ==================== LOGIN ====================

@dp.message(F.text.in_([
    get_text('uz', 'login'),
    get_text('ru', 'login')
]))
async def start_login(message: Message, state: FSMContext):
    """Loginni boshlash"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    await state.update_data(language=lang)
    
    await state.set_state(LoginStates.entering_client_code)
    await message.answer(
        get_text(lang, 'enter_client_code', CLIENT_CODE_PREFIX=CLIENT_CODE_PREFIX),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(LoginStates.entering_client_code, F.text)
async def process_client_code(message: Message, state: FSMContext):
    """Mijoz kodini qabul qilish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    await state.update_data(temp_client_code=message.text)
    await state.set_state(LoginStates.entering_phone_verify)
    
    await message.answer(
        get_text(lang, 'enter_phone_verify'),
        reply_markup=cancel_keyboard(lang, get_is_private(message))
    )


@dp.message(LoginStates.entering_phone_verify, F.text)
async def process_phone_verify(message: Message, state: FSMContext):
    """Telefon raqamini tekshirish va login"""
    data = await state.get_data()
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    if message.text == get_text(lang, 'cancel'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang, get_is_private(message))
        )
        return
    
    client_code = data['temp_client_code']
    
    # Brute-force himoyasi: check() (is_allowed, remaining_text) qaytaradi
    is_allowed, remaining = login_limiter.check(message.from_user.id)
    if not is_allowed:
        await message.answer(get_text(lang, 'login_blocked', remaining=remaining))
        await clear_state_keep_language(state, lang)
        return
    
    valid, msg, normalized_phone = Validators.validate_phone(message.text)
    if not valid:
        await message.answer(f"❌ {get_phone_validation_error(lang, msg)}\n\n{get_text(lang, 'enter_phone_verify')}")
        return

    user = await db.get_user_by_client_code(client_code, active_only=False)
    logger.debug(f"Login attempt: client_code={client_code}, user_found={bool(user)}")

    if not user:
        login_limiter.reset(message.from_user.id)
        await start_profile_completion(
            message,
            state,
            lang,
            client_code,
            None,
            {"phone": normalized_phone}
        )
        return

    stored_phone = user.get("phone")
    if not is_missing_profile_value(stored_phone):
        if normalize_phone_for_compare(stored_phone) != normalized_phone:
            login_limiter.record_failure(message.from_user.id)
            logger.warning(f"Failed login attempt: user_id={message.from_user.id}, client_code={client_code}")
            await message.answer(get_text(lang, 'login_failed'))
            await clear_state_keep_language(state, lang)
            bot_title = await bot.get_me()
            await message.answer(
                get_text(lang, 'welcome_new', bot_name=bot_title.first_name),
                reply_markup=welcome_keyboard(lang, get_is_private(message), bot_name=bot_title.first_name)
            )
            return

        provided_fields = {}
    else:
        provided_fields = {"phone": normalized_phone}

    missing_fields = db.get_missing_profile_fields(user)
    remaining_missing_fields = [
        field for field in missing_fields
        if field != "phone" and is_missing_profile_value(provided_fields.get(field))
    ]

    if "phone" in missing_fields or remaining_missing_fields:
        login_limiter.reset(message.from_user.id)
        await start_profile_completion(
            message,
            state,
            lang,
            user.get("client_code") or client_code,
            user,
            provided_fields
        )
        return

    if user.get('verification_status') != 'approved':
        login_limiter.reset(message.from_user.id)
        await answer_non_approved_login(message, state, lang, user, user.get("client_code") or client_code)
        return

    await finish_approved_login(message, state, lang, user, user.get("client_code") or client_code)
