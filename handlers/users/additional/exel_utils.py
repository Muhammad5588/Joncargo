import asyncio
import os
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from data.Async_sqlDataBase import data_db as db
from states import AdminStates
from loader import dp, bot
from utils.keyboards import admin_menu_keyboard
from utils.texts import get_text

@dp.message(AdminStates.user_exel_importing_process)
async def handle_excel_import(message: Message, state: FSMContext):
    # Faqat adminlar uchun
    if message.from_user.id not in await db.admin_view():
        return

    admin_user = await db.get_user_by_telegram_id(message.from_user.id)
    lang = admin_user['language'] if admin_user else 'uz'

    if message.text in (get_text(lang, 'back'), get_text(lang, 'cancel')):
        await state.set_state(AdminStates.in_admin_panel)
        await message.answer(
            get_text(lang, 'admin_welcome'),
            reply_markup=admin_menu_keyboard(lang, True)
        )
        return

    # Agar document yuborilmagan bo'lsa, state'ni tozalash
    if not message.document:
        await message.answer(get_text(lang, 'excel_file_prompt'))
        return

    file = message.document

    # Faqat Excel fayllarni qabul qilish
    if not file.file_name.endswith(('.xlsx', '.xls')):
        await message.answer("❌ Faqat Excel fayl (.xlsx yoki .xls) yuborish mumkin!")
        return
    
    # Faylni yuklab olish
    file_path = f"temp_{file.file_id}.xlsx"
    await message.bot.download(file, destination=file_path)
    
    # Background taskda import qilish
    asyncio.create_task(
        db.import_users_excel_background(
            file_path=file_path,
            bot=bot,
            admin_id=message.from_user.id
        )
    )

    await message.answer(
        "📥 Import boshlandi. Jarayon tugaganda natija shu chatga yuboriladi.",
        reply_markup=admin_menu_keyboard(lang, True)
    )
    await state.set_state(AdminStates.in_admin_panel)
    
    # Taskdan keyin faylni o'chirish
    async def cleanup():
        await asyncio.sleep(300)  # 5 daqiqadan keyin
        if os.path.exists(file_path):
            os.remove(file_path)
    
    asyncio.create_task(cleanup())