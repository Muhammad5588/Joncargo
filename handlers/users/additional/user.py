"""
User Handlers - Foydalanuvchi funksiyalari
"""
import logging
from aiogram import F
from loader import dp, bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, FSInputFile
from data.config import ADMIN_PPROFILE_USERNAME, CONTACT_PHONE_NUMBER, ISH_VAQTI, MANZIL, PUBLIC_CHANNEL_LINK
from data.config import (
    CHINA_ADDRESS_TEMPLATE,
    FEEDBACK_GROUP_ID
)
from data.Async_sqlDataBase import data_db as db
from states.AdminStates import UserStates
from utils.texts import get_text
from utils.keyboards import (
    main_menu_keyboard,
    back_keyboard,
    welcome_keyboard,
    yes_no_keyboard,
    feedback_reply_inline_keyboard,
    language_keyboard
)
from utils.formatters import (
    format_phone_display,
    format_verification_status,
    format_datetime
)
from utils.helpers import check_user_approved
from utils.language import clear_state_keep_language, resolve_language
import os


logger = logging.getLogger(__name__)



# ==================== PROFIL ====================

@dp.message(F.text.in_([
    get_text('uz', 'profile'),
    get_text('ru', 'profile')
]))
async def show_profile(message: Message, state: FSMContext):
    """Profilni ko'rsatish"""
    user, lang, is_approved = await check_user_approved(message, state)

    if not user or not is_approved:
        return
    
    profile_text = get_text(
        lang, 'profile_info',
        fullname=user['fullname'],
        client_code=user['client_code'],
        phone=format_phone_display(user['phone']),
        passport=user['passport_number'],
        birth_date=user['birth_date'],
        pinfl=user['pinfl'],
        address=user['address'],
        status=format_verification_status(user['verification_status'], lang),
        registered_at=format_datetime(user['registered_at'])
    )
    
    await message.answer(profile_text)
    


# ==================== XITOY MANZILI ====================

@dp.message(F.text.in_([
    get_text('uz', 'china_address'),
    get_text('ru', 'china_address')
]))
async def show_china_address(message: Message, state: FSMContext):
    """Xitoy sklad manzilini ko'rsatish"""
    user, lang, is_approved = await check_user_approved(message, state)

    if not user or not is_approved:
        return
    
    # Template rasmni yuborish
    if CHINA_ADDRESS_TEMPLATE and os.path.exists(CHINA_ADDRESS_TEMPLATE):
        try:
            caption_text = get_text(lang, 'china_address_info', client_code=user['client_code'])

            await message.answer_photo(
                FSInputFile(CHINA_ADDRESS_TEMPLATE),
                caption=caption_text
            )
        except:
            pass
    else:
        await message.answer(
            get_text(lang, 'china_address_info', client_code=user['client_code'])
        )

    # Agar tasdiqlagan bo'lsa
    if user['china_address_confirmed']:
        await message.answer(
            "✅ Siz allaqachon manzilni tasdiqlagansiz!"
            if lang == 'uz' else
            "✅ Вы уже подтвердили адрес!"
        )


@dp.message(UserStates.confirming_china_address, F.text)
async def confirm_china_address(message: Message, state: FSMContext):
    """Xitoy manzilini tasdiqlash"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    lang = user['language']
    
    if message.text == get_text(lang, 'yes'):
        # Tasdiqlash
        success = await db.confirm_china_address(user['id'])
        
        if success:
            await clear_state_keep_language(state, lang)
            await message.answer(
                get_text(lang, 'china_address_confirmed'),
                reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
            )
        else:
            await message.answer(get_text(lang, 'error_general'))
    
    elif message.text == get_text(lang, 'no'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'check_china_address_again'),
            reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
        )
    else:
        await message.answer(
            get_text(lang, 'choose_one_button'),
            reply_markup=yes_no_keyboard(lang)
        )


# ==================== FEEDBACK ====================

@dp.message(F.text.in_([
    get_text('uz', 'feedback'),
    get_text('ru', 'feedback')
]))
async def start_feedback(message: Message, state: FSMContext):
    """Feedback yozishni boshlash"""
    user, lang, is_approved = await check_user_approved(message, state)

    if not user or not is_approved:
        return
    
    await state.set_state(UserStates.entering_feedback)
    await message.answer(
        get_text(lang, 'enter_feedback'),
        reply_markup=back_keyboard(lang)
    )


@dp.message(UserStates.entering_feedback, F.text)
async def process_feedback(message: Message, state: FSMContext):
    """Feedbackni qabul qilish va guruhga yuborish"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'enter_language_prompt'),
            reply_markup=language_keyboard()
        )
        return

    lang = user['language']
    
    if message.text == get_text(lang, 'back'):
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'back_to_main'),
            reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
        )
        return
    
    # Feedbackni saqlash
    feedback_id = await db.save_feedback(
        user['id'],
        message.from_user.id,
        message.text
    )
    
    if not feedback_id:
        await message.answer(get_text(lang, 'error_general'))
        return
    
    # Feedback guruhga yuborish
    try:
        feedback_text = get_text(
            lang,
            'new_feedback',
            fullname=user['fullname'],
            client_code=user['client_code'],
            phone=format_phone_display(user['phone']),
            message=message.text
        )
        
        await bot.send_message(
            FEEDBACK_GROUP_ID,
            feedback_text,
            reply_markup=feedback_reply_inline_keyboard(
                message.from_user.id,
                feedback_id
            )
        )
        
        await clear_state_keep_language(state, lang)
        await message.answer(
            get_text(lang, 'feedback_sent'),
            reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
        )
    
    except Exception as e:
        logger.error(f"Send feedback to group error: {e}")
        await message.answer(get_text(lang, 'error_general'))


# ==================== KONTAKTLAR ====================

@dp.message(F.text.in_([
    get_text('uz', 'contacts'),
    get_text('ru', 'contacts')
]))
async def show_contacts(message: Message, state: FSMContext):
    """Kontaktlarni ko'rsatish"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
    
    # Agar user registered bo'lsa
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if user:
        lang = user['language']
    
    await message.answer(get_text(lang, 'contact_info', 
        CONTACT_PHONE_NUMBER=CONTACT_PHONE_NUMBER,
        PUBLIC_CHANNEL_LINK=PUBLIC_CHANNEL_LINK,
        ADMIN_PPROFILE_USERNAME=ADMIN_PPROFILE_USERNAME,
        MANZIL=MANZIL,
        ISH_VAQTI=ISH_VAQTI
    ))


# ==================== LOGOUT ====================

@dp.message(F.text.in_([
    get_text('uz', 'logout'),
    get_text('ru', 'logout')
]))
async def logout(message: Message, state: FSMContext):
    """Chiqish"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if user:
        lang = user['language']
        await state.update_data(language=lang)
        await message.answer(
            get_text(lang, 'logout_confirm'),
            reply_markup=yes_no_keyboard(lang)
        )
    else:
        lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)
        await clear_state_keep_language(state, lang)
        # Yangi foydalanuvchi
        bot_title = await bot.get_me()
        await message.answer(
            get_text(lang, 'welcome_new', bot_name=bot_title.first_name),
            reply_markup=welcome_keyboard(lang)
        )


@dp.message(F.text.in_(["✅ Ha", "✅ Да"]))
async def confirm_logout(message: Message, state: FSMContext):
    """Logout ni tasdiqlash"""
    lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)

    # Faqat logout confirm holatida
    current_state = await state.get_state()
    if current_state:
        return

    await clear_state_keep_language(state, lang)

    from aiogram.types import ReplyKeyboardRemove
    await message.answer(
        get_text(lang, 'logout_success'),
        reply_markup=ReplyKeyboardRemove()
    )
    await db.deactivate_user(message.from_user.id)
    bot_title = await bot.get_me()
    await message.answer(
        get_text(lang, 'welcome_new', bot_name=bot_title.first_name),
        reply_markup=welcome_keyboard(lang)
    )

@dp.message(F.text.in_(["❌ Yo'q", "❌ Нет"]))
async def cancel_logout(message: Message, state: FSMContext):
    """Logout ni bekor qilish"""
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user:
        lang = user['language']
    else:
        lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)

    await clear_state_keep_language(state, lang)
    await message.answer(
        get_text(lang, 'back_to_main'),
        reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
    )


# ==================== BEKOR QILISH ====================

@dp.message(F.text.in_([get_text('uz', 'cancel'), get_text('ru', 'cancel')]))
async def handle_cancel(message: Message, state: FSMContext):
    """Bekor qilish - har qanday holatdan chiqish"""
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user:
        lang = user['language']
    else:
        lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)

    await clear_state_keep_language(state, lang)
    if await db.is_user_registered(message.from_user.id):
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
        )
    else:
        await message.answer(
            get_text(lang, 'operation_cancelled'),
            reply_markup=welcome_keyboard(lang)
        )


# ==================== ORQAGA ====================

@dp.message(F.text.in_([get_text('uz', 'back'), get_text('ru', 'back')]))
async def handle_back(message: Message, state: FSMContext):
    """Orqaga qaytish"""
    
    if message.chat.id in await db.admin_view():
        from handlers.users.additional.admin import show_admin_panel
        await show_admin_panel(message, state)
        return
    
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user:
        lang = user['language']
    else:
        lang = await resolve_language(message, state, prefer_message_text=True, active_only=False)

    await clear_state_keep_language(state, lang)
    await message.answer(
        get_text(lang, 'back_to_main'),
        reply_markup=main_menu_keyboard(lang, await db.is_admin(message.from_user.id))
    )

