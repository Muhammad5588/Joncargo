"""
Admin Handlers - Admin Panel va Boshqaruv
"""
import os
import logging
import asyncio
from datetime import datetime
import pandas as pd
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
)

from loader import dp, bot

from data.config import (
    ADMIN_PPROFILE_USERNAME,
    VERIFIED_GROUP_ID,
)
from data.Async_sqlDataBase import data_db as db
from states import AdminStates
from utils.texts import get_text
from utils.keyboards import (
    admin_menu_keyboard,
    main_menu_keyboard,
    back_keyboard,
    confirm_keyboard,
    broadcast_confirm_inline_keyboard,
    user_management_inline_keyboard,
)
from utils.formatters import (
    format_phone_display, 
    format_datetime,
    format_verification_status
)

from data.config import CHINA_ADDRESS_TEMPLATE, CHINA_ADDRESS_TEMPLATE_TEXT
from aiogram.types import FSInputFile
from utils.audit_log import audit_logger
from utils.validators import Validators
import os

logger = logging.getLogger(__name__)


# Helper: Guruhlarda keyboard yuborilmasligi uchun
def get_is_private(message_or_callback) -> bool:
    """Check if message/callback is from private chat"""
    if hasattr(message_or_callback, 'message'):
        # CallbackQuery case
        return message_or_callback.message.chat.type == 'private'
    elif hasattr(message_or_callback, 'chat'):
        # Message case
        return message_or_callback.chat.type == 'private'
    return True


async def get_admin_lang(user_id: int) -> str:
    user = await db.get_user_by_telegram_id(user_id)
    return user['language'] if user else 'uz'


# ==================== ADMIN PANEL ====================

async def show_admin_panel(message: Message, state: FSMContext):
    """Admin panelni ko'rsatish"""
    if not await db.is_admin(message.from_user.id):
        # Try to show access_denied in user's language if available
        user = await db.get_user_by_telegram_id(message.from_user.id)
        u_lang = user['language'] if user else 'uz'
        await message.answer(get_text(u_lang, 'access_denied'))
        return
    
    await state.set_state(AdminStates.in_admin_panel)
    # Set admin language from DB if available
    user = await db.get_user_by_telegram_id(message.from_user.id)
    data = await state.get_data()
    lang = user['language'] if user else data.get('language', 'uz')
    await state.update_data(language=lang)
    await message.answer(
        get_text(lang, 'admin_welcome'),
        reply_markup=admin_menu_keyboard(lang, get_is_private(message))
    )

# ==================== APPROVAL / REJECTION ====================

@dp.callback_query(F.data.startswith("approve:"))
async def approve_user_callback(callback: CallbackQuery):
    """Foydalanuvchini tasdiqlash"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        # respond in admin's language if possible
        admin_user = await db.get_user_by_telegram_id(callback.from_user.id)
        a_lang = admin_user['language'] if admin_user else 'uz'
        await callback.answer(get_text(a_lang, 'access_denied'), show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":")[1])
        
        # Tasdiqlash
        success = await db.approve_user(user_id)
        
        if success:
            user = await db.get_user_by_id(user_id)

            if user and user['telegram_id']:
                # Foydalanuvchiga xabar va verified guruhga yuborishni background taskda ishlatish
                async def send_notifications():
                    # Foydalanuvchiga xabar
                    try:
                        await bot.send_message(
                            user['telegram_id'],
                            get_text(
                                user['language'],
                                'registration_approved',
                                client_code=user['client_code'],
                                phone=format_phone_display(user['phone'])
                            ),
                            reply_markup=main_menu_keyboard(user['language'], is_private=True)
                        )
                    except:
                        logger.warning(f"Could not send approval message to user {user_id}")

                    # Xitoy manzilini yuborish
                    try:

                        # Manzil matni
                        address_text = CHINA_ADDRESS_TEMPLATE_TEXT.format(
                            client_code=user['client_code']
                        )
                        # Template rasmni yuborish
                        if CHINA_ADDRESS_TEMPLATE and os.path.exists(CHINA_ADDRESS_TEMPLATE):
                            try:
                                await bot.send_photo(
                                    user['telegram_id'],
                                    FSInputFile(CHINA_ADDRESS_TEMPLATE),
                                    caption=address_text
                                )
                            except:
                                pass

                        # Muhim ogohlantirish xabari
                        
                        warning_message = (
                            "⚠️ MUHIM OGOHLANTIRISH!\n\n"
                            "Xitoy manzilini to'g'ri kiritganingizni tekshiring va "
                            f"{ADMIN_PPROFILE_USERNAME} adminga yozib, manzilni tasdiqlatishingizni so'raymiz.\n\n"
                            "❗️ Admin tomonidan tasdiqlanmagan manzilga yuborilgan yuklar "
                            "uchun javobgarlik o'z zimmamizga olinmaydi!\n\n"
                            f"📞 Manzilni tasdiqlash uchun: {ADMIN_PPROFILE_USERNAME}"
                            if user['language'] == 'uz' else
                            "⚠️ ВАЖНОЕ ПРЕДУПРЕЖДЕНИЕ!\n\n"
                            "Проверьте правильность указанного адреса в Китае и "
                            f"свяжитесь с {ADMIN_PPROFILE_USERNAME} для подтверждения адреса.\n\n"
                            "❗️ Мы не несем ответственности за грузы, "
                            "отправленные на адрес, не подтвержденный администратором!\n\n"
                            f"📞 Для подтверждения адреса: {ADMIN_PPROFILE_USERNAME}"
                        )
                        await bot.send_message(user['telegram_id'], warning_message)

                    except Exception as e:
                        logger.warning(f"Could not send China address to user {user_id}: {e}")

                    # Verified guruhga yuborish
                    await send_to_verified_group(user)

                # Background taskda yuborish
                asyncio.create_task(send_notifications())

            # Callback javob
            # Notify admin in their language
            admin_user = await db.get_user_by_telegram_id(callback.from_user.id)
            a_lang = admin_user['language'] if admin_user else 'uz'
            await callback.answer(get_text(a_lang, 'user_approved'), show_alert=True)
            
            # Audit log
            await audit_logger.log(
                admin_id=callback.from_user.id,
                action="approve_user",
                target_type="user",
                target_id=str(user_id),
                details=f"User {user_id} tasdiqlandi"
            )
            
            # Xabarni tahrirlash
            try:
                await callback.message.edit_text(
                    callback.message.text + "\n\n✅ TASDIQLANDI",
                    reply_markup=None
                )
                
            except:
                pass
        else:
            await callback.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    except Exception as e:
        logger.error(f"Approve callback error: {e}")
        await callback.answer("❌ Xatolik!", show_alert=True)


@dp.callback_query(F.data.startswith("reject:"))
async def reject_user_callback(callback: CallbackQuery, state: FSMContext):
    """Foydalanuvchini rad etish - sabab so'rash"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        user_id = int(callback.data.split(":")[1])

        # State ga saqlash (guruhda ham, private chatda ham)
        await state.update_data(
            rejecting_user_id=user_id,
            rejection_message_id=callback.message.message_id,
            rejection_chat_id=callback.message.chat.id
        )
        await state.set_state(AdminStates.entering_rejection_reason)

        # Guruhda yoki private chatda - bir xil javob
        reply_text = f"❌ User ID {user_id} ni rad etish uchun sabab yozing:"

        await callback.message.reply(reply_text)
        await callback.answer()

    except Exception as e:
        logger.error(f"Reject callback error: {e}")
        await callback.answer("❌ Xatolik!", show_alert=True)


@dp.message(AdminStates.entering_rejection_reason, F.text)
async def process_rejection_reason(message: Message, state: FSMContext):
    """Rad etish sababini qabul qilish"""
    data = await state.get_data()
    user_id = data.get('rejecting_user_id')
    rejection_message_id = data.get('rejection_message_id')
    rejection_chat_id = data.get('rejection_chat_id')

    # Determine admin language
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    lang = admin_user['language'] if admin_user else 'uz'

    if message.text == get_text(lang, 'back'):
        await state.clear()
        await message.answer(
            get_text(lang, 'operation_cancelled') if lang == 'uz' else get_text(lang, 'operation_cancelled'),
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
        return

    if not user_id:
        await message.answer("❌ Xatolik: User ID topilmadi")
        return

    reason = message.text.strip()

    # Rad etish
    success = await db.reject_user(user_id, reason)

    if success:
        user = await db.get_user_by_id(user_id)

        if user and user['telegram_id']:
            # Foydalanuvchiga xabar
            try:
                await bot.send_message(
                    user['telegram_id'],
                    get_text(user['language'], 'registration_rejected', reason=reason)
                )
            except:
                logger.warning(f"Could not send rejection message to user {user_id}")

        # Asl xabarni yangilash (guruhda yoki private chatda)
        if rejection_message_id and rejection_chat_id:
            try:
                # Tugmalarni olib tashlash
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=rejection_chat_id,
                        message_id=rejection_message_id,
                        reply_markup=None
                    )
                except:
                    pass

                # Guruhga rad etilgani haqida xabar yuborish
                await bot.send_message(
                    rejection_chat_id,
                    f"❌ RAD ETILDI\nSabab: {reason}",
                    reply_to_message_id=rejection_message_id
                )
            except Exception as e:
                logger.error(f"Error updating rejection message: {e}")

        await message.answer(
            f"✅ User ID {user_id} rad etildi!\nSabab: {reason}"
        )
        
        # Audit log
        await audit_logger.log(
            admin_id=message.from_user.id,
            action="reject_user",
            target_type="user",
            target_id=str(user_id),
            details=f"User {user_id} rad etildi. Sabab: {reason}"
        )
    else:
        await message.answer("❌ Xatolik yuz berdi!")

    await state.clear()


async def send_to_verified_group(user: dict):
    """Tasdiqlangan foydalanuvchini verified guruhga yuborish (ALBUM BILAN)"""
    from aiogram.types import InputMediaPhoto

    try:
        text = f"""
✅ YANGI TASDIQLANGAN MIJOZ

👤 {user['fullname']}
🆔 {user['client_code'] or 'Hali kod yaratilmagan'}
📱 {format_phone_display(user['phone'])}
🔖 Pasport: {user['passport_number']}
📅 Tug'ilgan: {user['birth_date']}
🔢 PINFL: {user['pinfl']}
📍 {user['address']}

📅 Tasdiqlangan: {format_datetime(user.get('verified_at', 'now'))}
"""

        # Rasmlar ro'yxati
        media = []

        # Pasport old rasmi
        if user.get('passport_front_file_id'):
            media.append(
                InputMediaPhoto(media=user['passport_front_file_id'])
            )

        # Pasport orqa rasmi (agar mavjud bo'lsa)
        if user.get('passport_back_file_id') and user['passport_back_file_id'] != user.get('passport_front_file_id'):
            media.append(
                InputMediaPhoto(media=user['passport_back_file_id'])
            )

        # Album yuborish
        if media:
            # Birinchi rasmga captionni qo'shamiz
            media[0].caption = text
            await bot.send_media_group(VERIFIED_GROUP_ID, media)
        else:
            # Agar rasm bo'lmasa, faqat text yuboramiz
            await bot.send_message(VERIFIED_GROUP_ID, text)

    except Exception as e:
        logger.error(f"Send to verified group error: {e}")


# ==================== BARCHA FOYDALANUVCHILARNI KO'RISH ====================

@dp.message(F.text.contains("👥") | F.text.contains("Foydalanuvchilar") | F.text.contains("пользовател"))
async def show_all_users(message: Message, state: FSMContext):
    """Barcha foydalanuvchilarni ko'rsatish"""
    if not await db.is_admin(message.from_user.id):
        user = await db.get_user_by_telegram_id(message.from_user.id)
        u_lang = user['language'] if user else 'uz'
        await message.answer(get_text(u_lang, 'access_denied'))
        return

    # Foydalanuvchilar soni
    user_count = await db.user_count()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    users_file = f"users_export_{timestamp}.xlsx"
    template_file = f"users_import_template_{timestamp}.xlsx"

    try:
        users = await db.get_all_users_for_excel()

        users_df = pd.DataFrame(users)
        if users_df.empty:
            users_df = pd.DataFrame(columns=[
                'id', 'telegram_id', 'client_code', 'fullname', 'phone',
                'passport_number', 'birth_date', 'pinfl', 'address',
                'verification_status', 'registered_at', 'verified_at', 'language'
            ])
        users_df.to_excel(users_file, index=False)

        template_df = pd.DataFrame([{
            'code_str': '',
            'fullname_passport': '',
            'phone_number': '',
            'passport_series': '',
            'birth_date': '',
            'passport_pinfl': '',
            'address_region': '',
            'telegram_id': '',
            'language': 'uz'
        }])
        template_df.to_excel(template_file, index=False)

        await message.answer(
            f"📊 FOYDALANUVCHILAR STATISTIKASI\n\n"
            f"👥 Jami: {user_count} ta\n\n"
            f"1) Hozirgi foydalanuvchilar Excel fayli yuboriladi\n"
            f"2) Import uchun shablon Excel yuboriladi\n"
            f"3) To'ldirilgan Excel faylni shu yerga yuboring"
        )

        await message.answer_document(
            document=FSInputFile(users_file),
            caption="📥 Hozirgi foydalanuvchilar ro'yxati (Excel)"
        )
        await message.answer_document(
            document=FSInputFile(template_file),
            caption=(
                "📋 Import shabloni (Excel)\n"
                "Ustunlar: code_str, fullname_passport, phone_number, passport_series, "
                "birth_date, passport_pinfl, address_region, telegram_id"
            )
        )
    except Exception as e:
        logger.error(f"Users export/template error: {e}")
        await message.answer("❌ Excel fayllarni tayyorlashda xatolik yuz berdi")
    finally:
        for file_path in (users_file, template_file):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    # Use admin language for back keyboard
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    a_lang = admin_user['language'] if admin_user else 'uz'
    await message.answer(
        "📤 Endi to'ldirilgan Excel faylni yuboring yoki ⬅️ Orqaga bosing.",
        reply_markup=back_keyboard(a_lang, get_is_private(message))
    )
    await state.set_state(AdminStates.user_exel_importing_process)


@dp.message(F.text.in_([
    get_text('uz', 'add_user'),
    get_text('ru', 'add_user')
]))
async def start_manual_add_user(message: Message, state: FSMContext):
    """Admin tomonidan qo'lda foydalanuvchi qo'shishni boshlash"""
    if not await db.is_admin(message.from_user.id):
        user = await db.get_user_by_telegram_id(message.from_user.id)
        u_lang = user['language'] if user else 'uz'
        await message.answer(get_text(u_lang, 'access_denied'))
        return

    # Use admin language for prompts
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    a_lang = admin_user['language'] if admin_user else 'uz'
    await state.set_state(AdminStates.manual_user_fullname)
    await message.answer(
        "➕ Qo'lda mijoz qo'shish\n\n"
        "1/6 F.I.O kiriting (masalan: Ali Valiyev)",
        reply_markup=back_keyboard(a_lang, get_is_private(message))
    )


@dp.message(AdminStates.manual_user_fullname, F.text)
async def manual_user_fullname(message: Message, state: FSMContext):
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    a_lang = admin_user['language'] if admin_user else 'uz'
    if message.text == get_text(a_lang, 'back'):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer(get_text(a_lang, 'admin_welcome'), reply_markup=admin_menu_keyboard(a_lang, get_is_private(message)))
        return

    valid, msg, fullname = Validators.validate_fullname(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(fullname=fullname)
    await state.set_state(AdminStates.manual_user_phone)
    await message.answer("2/6 Telefon raqam kiriting (masalan: +998901234567)")


@dp.message(AdminStates.manual_user_phone, F.text)
async def manual_user_phone(message: Message, state: FSMContext):
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    a_lang = admin_user['language'] if admin_user else 'uz'
    if message.text == get_text(a_lang, 'back'):
        await state.set_state(AdminStates.manual_user_fullname)
        await message.answer("1/6 F.I.O kiriting:")
        return

    valid, msg, phone = Validators.validate_phone(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(phone=phone)
    await state.set_state(AdminStates.manual_user_passport)
    await message.answer("3/6 Pasport seriyasi kiriting (masalan: AA1234567)")


@dp.message(AdminStates.manual_user_passport, F.text)
async def manual_user_passport(message: Message, state: FSMContext):
    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    a_lang = admin_user['language'] if admin_user else 'uz'
    if message.text == get_text(a_lang, 'back'):
        await state.set_state(AdminStates.manual_user_phone)
        await message.answer("2/6 Telefon raqam kiriting:")
        return

    valid, msg, passport = Validators.validate_passport_number(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(passport_number=passport)
    await state.set_state(AdminStates.manual_user_birth_date)
    await message.answer("4/6 Tug'ilgan sanani kiriting (masalan: 15.03.1990)")


@dp.message(AdminStates.manual_user_birth_date, F.text)
async def manual_user_birth_date(message: Message, state: FSMContext):
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.manual_user_passport)
        await message.answer("3/6 Pasport seriyasi kiriting:")
        return

    valid, msg, birth_date, _, _ = Validators.validate_birth_date(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(birth_date=birth_date)
    await state.set_state(AdminStates.manual_user_pinfl)
    await message.answer("5/6 PINFL kiriting (14 xonali)")


@dp.message(AdminStates.manual_user_pinfl, F.text)
async def manual_user_pinfl(message: Message, state: FSMContext):
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.manual_user_birth_date)
        await message.answer("4/6 Tug'ilgan sanani kiriting:")
        return

    valid, msg, pinfl = Validators.validate_pinfl(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(pinfl=pinfl)
    await state.set_state(AdminStates.manual_user_address)
    await message.answer("6/6 To'liq manzil kiriting")


@dp.message(AdminStates.manual_user_address, F.text)
async def manual_user_address(message: Message, state: FSMContext):
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.manual_user_pinfl)
        await message.answer("5/6 PINFL kiriting:")
        return

    valid, msg, address = Validators.validate_address(message.text)
    if not valid:
        await message.answer(f"❌ {msg}\n\nQayta kiriting:")
        return

    await state.update_data(address=address)
    data = await state.get_data()

    preview = (
        "✅ Ma'lumotlarni tekshiring:\n\n"
        f"👤 F.I.O: {data['fullname']}\n"
        f"📱 Telefon: {data['phone']}\n"
        f"🔖 Pasport: {data['passport_number']}\n"
        f"📅 Tug'ilgan sana: {data['birth_date']}\n"
        f"🔢 PINFL: {data['pinfl']}\n"
        f"📍 Manzil: {address}\n\n"
        "Tasdiqlaysizmi?"
    )
    await state.set_state(AdminStates.manual_user_confirm)
    await message.answer(preview, reply_markup=confirm_keyboard(lang, get_is_private(message)))


@dp.message(AdminStates.manual_user_confirm, F.text)
async def manual_user_confirm(message: Message, state: FSMContext):
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'cancel'), get_text('ru', 'cancel'), get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer("❌ Qo'lda mijoz qo'shish bekor qilindi", reply_markup=admin_menu_keyboard(lang, get_is_private(message)))
        return

    if message.text not in (get_text('uz', 'confirm'), get_text('ru', 'confirm')):
        await message.answer(get_text(lang, 'confirm_or_cancel'))
        return

    data = await state.get_data()
    client_code = await db.generate_client_code()

    user_data = {
        'fullname': data['fullname'],
        'phone': data['phone'],
        'passport_number': data['passport_number'],
        'birth_date': data['birth_date'],
        'pinfl': data['pinfl'],
        'address': data['address'],
        'language': lang
    }

    success, msg, _ = await db.register_user_with_code(
        client_code=client_code,
        telegram_id=None,
        user_data=user_data
    )

    if success:
        await message.answer(
            f"✅ Mijoz muvaffaqiyatli qo'shildi\n\n🆔 Client code: {client_code}",
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
    else:
        await message.answer(
            f"❌ Mijoz qo'shishda xatolik: {msg}",
            reply_markup=admin_menu_keyboard('uz', get_is_private(message))
        )

    await state.set_state(AdminStates.in_admin_panel)


# ==================== FOYDALANUVCHINI TO'LIQ KO'RISH ====================

@dp.callback_query(F.data.startswith("viewuser:"))
async def view_user_details(callback: CallbackQuery):
    """Foydalanuvchi to'liq ma'lumotlarini ko'rish"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":")[1])
        user = await db.get_user_by_id(user_id)
        
        if not user:
            await callback.answer("❌ Foydalanuvchi topilmadi!", show_alert=True)
            return
        
        # To'liq ma'lumotlar
        full_info = f"""
👤 TO'LIQ MA'LUMOTLAR

🆔 ID: {user['id']}
👨‍💼 F.I.O: {user['fullname']}
🔐 Mijoz kodi: {user['client_code']}
📱 Telefon: {format_phone_display(user['phone'])}
🔖 Pasport: {user['passport_number']}
📅 Tug'ilgan: {user['birth_date']}
🔢 PINFL: {user['pinfl']}
📍 Manzil: {user['address']}

✅ Holat: {format_verification_status(user['verification_status'], 'uz')}
🇨🇳 Xitoy manzil: {'✅ Tasdiqlangan' if user['china_address_confirmed'] else '❌ Tasdiqlanmagan'}
🌐 Til: {user['language'].upper()}

📅 Ro'yxat: {format_datetime(user['registered_at'])}
📅 Oxirgi kirish: {format_datetime(user['last_login']) if user['last_login'] else '—'}

💬 Telegram ID: {user['telegram_id'] if user['telegram_id'] else '—'}
"""
        
        # Pasport rasmlar
        photos_text = "\n📸 Pasport rasmlari:\n"
        if user['passport_front_photo']:
            photos_text += f"• Old: {user['passport_front_photo']}\n"
        if user['passport_back_photo']:
            photos_text += f"• Orqa: {user['passport_back_photo']}\n"
        
        await callback.message.answer(full_info + photos_text)
        await callback.answer()
    
    except Exception as e:
        logger.error(f"View user error: {e}")
        await callback.answer("❌ Xatolik!", show_alert=True)



# ==================== USER QIDIRISH ====================

@dp.message(F.text.in_([
    get_text('uz', 'search_user'),
    get_text('ru', 'search_user')
]))
async def start_user_search(message: Message, state: FSMContext):
    """User qidirishni boshlash"""
    if not await db.is_admin(message.from_user.id):
        await message.answer(get_text(await get_admin_lang(message.from_user.id), 'access_denied'))
        return

    lang = await get_admin_lang(message.from_user.id)
    
    await state.set_state(AdminStates.searching_user)
    await message.answer(
        get_text(lang, 'enter_user_search'),
        reply_markup=back_keyboard(lang, get_is_private(message))
    )


@dp.message(AdminStates.searching_user, F.text)
async def process_user_search(message: Message, state: FSMContext):
    """User ni qidirish"""
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer(
            get_text(lang, 'admin_welcome'),
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
        return
    
    query = message.text.strip()
    users = await db.search_users(query)
    
    if not users:
        await message.answer(get_text(lang, 'user_not_found'), reply_markup=back_keyboard(lang, get_is_private(message)))
        return
    
    # Natijalarni ko'rsatish
    for user in users:
        user_info = get_text(
            lang, 'admin_user_info',
            user_id=user['id'],
            fullname=user['fullname'],
            phone=format_phone_display(user['phone']),
            passport=user['passport_number'],   
            birth_date=user['birth_date'],
            pinfl=user['pinfl'],
            address=user['address'],
            status=user['verification_status'],
            registered_at=format_datetime(user['registered_at'])
        )
        
        await message.answer(
            user_info,
            reply_markup=user_management_inline_keyboard(user['id'], lang)
        )
    await state.clear()

# ==================== BROADCAST ====================

@dp.message(F.text.in_([
    get_text('uz', 'broadcast'),
    get_text('ru', 'broadcast')
]))
async def start_broadcast(message: Message, state: FSMContext):
    """Broadcast ni boshlash"""
    if not await db.is_admin(message.from_user.id):
        await message.answer(get_text(await get_admin_lang(message.from_user.id), 'access_denied'))
        return

    lang = await get_admin_lang(message.from_user.id)
    
    await state.set_state(AdminStates.entering_broadcast_message)
    await message.answer(
        get_text(lang, 'enter_broadcast_message'),
        reply_markup=back_keyboard(lang, get_is_private(message))
    )


@dp.message(AdminStates.entering_broadcast_message, F.text)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Broadcast xabarini qabul qilish"""
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer(
            get_text(lang, 'admin_welcome'),
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
        return
    
    broadcast_text = message.text
    
    # Foydalanuvchilar sonini olish
    user_count = await db.user_count()
    
    # Tasdiqlash
    await state.update_data(broadcast_message=broadcast_text)
    
    await message.answer(
        get_text('uz', 'broadcast_confirm', count=user_count, message=broadcast_text),
        reply_markup=broadcast_confirm_inline_keyboard('uz')
    )


@dp.callback_query(F.data == "broadcast:confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Broadcast ni tasdiqlash va yuborish"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    data = await state.get_data()
    broadcast_text = data.get('broadcast_message')
    
    if not broadcast_text:
        await callback.answer("❌ Xabar topilmadi!", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    
    # Yuborish jarayoni
    await callback.message.answer(get_text('uz', 'broadcast_sending'))
    
    users = await db.get_all_active_users()
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            if not user:
                continue
            await bot.send_message(user['telegram_id'], broadcast_text)
            sent += 1
            await asyncio.sleep(0.05)  # Rate limit
        except Exception as e:
            logger.warning(f"Broadcast to {user['telegram_id']} failed: {e}")
            failed += 1
    
    # Natija
    await callback.message.answer(
        get_text('uz', 'broadcast_completed', sent=sent, total=len(users)),
        reply_markup=admin_menu_keyboard('uz', get_is_private(callback))
    )
    
    await state.set_state(AdminStates.in_admin_panel)


@dp.callback_query(F.data == "broadcast:cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Broadcast ni bekor qilish"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("❌ Bekor qilindi")
    
    await state.set_state(AdminStates.in_admin_panel)
    await callback.message.answer(
        get_text(await get_admin_lang(callback.from_user.id), 'admin_welcome'),
        reply_markup=admin_menu_keyboard(await get_admin_lang(callback.from_user.id), get_is_private(callback))
    )


# ==================== DATABASE YUKLASH ====================

@dp.message(F.text.in_([
    get_text('uz', 'upload_db'),
    get_text('ru', 'upload_db')
]))
async def start_db_upload(message: Message, state: FSMContext):
    """Database yuklashni boshlash"""
    if not await db.is_admin(message.from_user.id):
        await message.answer(get_text(await get_admin_lang(message.from_user.id), 'access_denied'))
        return

    lang = await get_admin_lang(message.from_user.id)
    
    await state.set_state(AdminStates.uploading_database)
    await message.answer(
        get_text(lang, 'upload_file_prompt'),
        reply_markup=back_keyboard(lang, get_is_private(message))
    )


@dp.message(AdminStates.uploading_database, F.document)
async def process_db_upload(message: Message, state: FSMContext):
    """Database faylini yuklash"""
    if not await db.is_admin(message.from_user.id):
        await message.answer(get_text(await get_admin_lang(message.from_user.id), 'access_denied'))
        return

    lang = await get_admin_lang(message.from_user.id)
    
    doc = message.document
    
    if not doc.file_name.endswith(('.xlsx', '.xls', '.csv')):
        await message.answer(get_text(lang, 'invalid_file_format'))
        return
    
    try:
        # Faylni yuklab olish
        file = await bot.get_file(doc.file_id)
        file_path = f"temp_{doc.file_name}"
        
        await bot.download_file(file.file_path, file_path)
        
        # Import qilish
        success, msg = await db.import_shipments_from_file(file_path)
        
        # Temp faylni o'chirish
        if os.path.exists(file_path):
            os.remove(file_path)
        
        if success:
            await message.answer(
                f"{get_text(lang, 'database_uploaded')}\n{msg}",
                reply_markup=admin_menu_keyboard(lang, get_is_private(message))
            )
        else:
            await message.answer(
                f"{get_text(lang, 'upload_error')}: {msg}",
                reply_markup=admin_menu_keyboard(lang, get_is_private(message))
            )
        
        await state.set_state(AdminStates.in_admin_panel)
    
    except Exception as e:
        logger.error(f"DB upload error: {e}")
        await message.answer(
            f"{get_text(lang, 'upload_error')}: {str(e)}",
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )


# ==================== ADMIN TREK QIDIRISH ====================

@dp.message(F.text.in_([
    get_text('uz', 'admin_search'),
    get_text('ru', 'admin_search')
]))
async def start_admin_search(message: Message, state: FSMContext):
    """Admin trek qidirishni boshlash"""
    if not await db.is_admin(message.from_user.id):
        await message.answer(get_text(await get_admin_lang(message.from_user.id), 'access_denied'))
        return

    lang = await get_admin_lang(message.from_user.id)
    
    await state.set_state(AdminStates.admin_searching_trek)
    await message.answer(
        get_text(lang, 'enter_trek_code'),
        reply_markup=back_keyboard(lang, get_is_private(message))
    )


@dp.message(AdminStates.admin_searching_trek, F.text)
async def process_admin_search(message: Message, state: FSMContext):
    """Admin trek qidirish (full access)"""
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer(
            get_text(lang, 'admin_welcome'),
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
        return
    
    codes = [c.strip() for c in message.text.replace(',', ' ').split() if c.strip()]
    
    found_any = False
    
    for code in codes:
        results = await db.search_by_tracking_code(code)
        
        if results:
            found_any = True
            for item in results:
                response = f"{get_text(lang, 'shipment_found')} (Trek: {code})\n\n"
                response += get_text(
                    lang, 'shipment_details',
                    name=item['shipping_name'],
                    tracking=item['tracking_code'],
                    package=item['package_number'],
                    weight=item['weight'],
                    quantity=item['quantity'],
                    flight=item['flight']
                )
                response += f"\n👤 Customer: {item['customer_code']}"
                
                await message.answer(response)
        else:
            await message.answer(f"{get_text(lang, 'trek_not_found')}: {code}")
    
    if not found_any:
        await message.answer("❌ Hech qanday yuk topilmadi")


# ==================== FEEDBACK REPLY ====================

@dp.callback_query(F.data.startswith("feedback_reply:"))
async def feedback_reply_callback(callback: CallbackQuery, state: FSMContext):
    """Feedbackga javob berish"""
    # Admin tekshiruvi
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    try:
        parts = callback.data.split(":")
        user_telegram_id = int(parts[1])
        feedback_id = int(parts[2])
        
        # State ga saqlash
        await state.update_data(
            replying_to_user=user_telegram_id,
            replying_to_feedback=feedback_id
        )
        await state.set_state(AdminStates.replying_to_feedback)
        
        await callback.message.answer(
            "💬 Javobingizni yozing:",
            reply_markup=back_keyboard('uz', get_is_private(callback))
        )
        
        await callback.answer()
    
    except Exception as e:
        logger.error(f"Feedback reply callback error: {e}")
        await callback.answer("❌ Xatolik!", show_alert=True)


@dp.message(AdminStates.replying_to_feedback, F.text)
async def process_feedback_reply(message: Message, state: FSMContext):
    """Admin javobini yuborish"""
    data = await state.get_data()
    user_telegram_id = data.get('replying_to_user')
    feedback_id = data.get('replying_to_feedback')
    
    lang = await get_admin_lang(message.from_user.id)

    if message.text in (get_text('uz', 'back'), get_text('ru', 'back')):
        await state.clear()
        await message.answer(
            get_text(lang, 'admin_welcome'),
            reply_markup=admin_menu_keyboard(lang, get_is_private(message))
        )
        return
    
    if not user_telegram_id or not feedback_id:
        await message.answer("❌ Xatolik: Ma'lumotlar topilmadi")
        return
    
    reply_text = message.text
    
    # Database ga saqlash
    success = await db.save_feedback_reply(feedback_id, reply_text)
    
    if success:
        # User ga yuborish
        try:
            user = await db.get_user_by_telegram_id(user_telegram_id)
            if user:
                await bot.send_message(
                    user_telegram_id,
                    get_text(user['language'], 'feedback_reply', reply=reply_text)
                )
                
                await message.answer(
                    "✅ Javob foydalanuvchiga yuborildi!"
                )
            else:
                await message.answer("❌ Foydalanuvchi topilmadi")
        
        except Exception as e:
            logger.error(f"Send reply error: {e}")
            await message.answer(f"❌ Yuborishda xatolik: {e}")
    else:
        await message.answer("❌ Saqlashda xatolik")
    
    await state.clear()

