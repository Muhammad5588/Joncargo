import re
import aiosqlite
from aiogram import F
from aiogram.filters                import Command, CommandStart
from aiogram.types                  import Message, CallbackQuery, ReplyKeyboardRemove
from loader                         import dp, bot
from data.Async_sqlDataBase         import data_db as db
from data.config                    import DB_FILE
from keyboards.inline.admin_page    import builder_admin
from aiogram.fsm.context          import FSMContext

from utils.formatters import format_verification_status
from utils.keyboards import main_menu_keyboard, welcome_keyboard, language_keyboard
from utils.language import clear_state_keep_language
from utils.texts import get_text


LANGUAGE_OPTION_BUTTONS = ["🇺🇿 O'zbek", "🇷🇺 Русский"]


async def show_language_selection(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Iltimos, tilni tanlang / Пожалуйста, выберите язык:",
        reply_markup=language_keyboard()
    )


@dp.message(Command(commands='lang'))
async def command_language_handler(message: Message, state: FSMContext):
    await show_language_selection(message, state)


@dp.message(F.text.in_([
    get_text('uz', 'language'),
    get_text('ru', 'language')
]))
async def select_language(message: Message, state: FSMContext):
    await show_language_selection(message, state)


@dp.message(F.text.in_(LANGUAGE_OPTION_BUTTONS))
async def process_language_selection(message: Message, state: FSMContext):
    user = await db.get_user_by_telegram_id(message.from_user.id)
    stored_user = user or await db.get_user_by_telegram_id(message.from_user.id, active_only=False)
    is_admin = await db.is_admin(message.from_user.id)

    if message.text == "🇺🇿 O'zbek":
        new_lang = 'uz'
    else:
        new_lang = 'ru'

    await state.clear()
    await state.update_data(language=new_lang)

    if stored_user:
        async with aiosqlite.connect(DB_FILE) as db_conn:
            await db_conn.execute(
                'UPDATE users SET language = ? WHERE id = ?',
                (new_lang, stored_user['id'])
            )
            await db_conn.commit()

    await message.answer(get_text(new_lang, f'language_changed_{new_lang}'))

    if is_admin:
        from handlers.users.additional.admin import show_admin_panel

        await show_admin_panel(message, state)
        return

    if user:
        await message.answer(
            get_text(new_lang, 'back_to_main'),
            reply_markup=main_menu_keyboard(new_lang, await db.is_admin(message.from_user.id))
        )
        return

    bot_title = await bot.get_me()
    await message.answer(
        get_text(new_lang, 'welcome_new', bot_name=bot_title.first_name),
        reply_markup=welcome_keyboard(new_lang)
    )


@dp.message(CommandStart()) 
async def command_start_handler(message: Message, command: CommandStart, state: FSMContext) -> None:
    if message.chat.type == 'private':
        args = command.args or ''
        me = await bot.get_me()
        await db.delete_rejected_users()  # Rejected foydalanuvchilarni o'chirish
        # Agar deep link bor bo'lsa
        if args and not(message.chat.id in await db.admin_view()):
            match = re.match(r"UMTS-[A-Za-z0-9]{12}$", args)
            if match:
                code = match.group(0)
                baseCode = await db.check_code(code)
                if baseCode:
                    await db.delete_code(code)
                    await db.admin_plus(message.chat.id)
                else:
                    await message.reply("Mavjud bo'lmagan kod.")
        
        # Umumiy start jarayoni
        if message.chat.id == (await db.admin_view())[0]:
            from handlers.users.additional.admin import show_admin_panel

            await message.answer(
                text=f"{message.from_user.mention_html()} -- <b>⚜️Admin aka⚜️</b> Assalom-u alaykum Bot xizmatingizda!\n🆔: <code>{message.chat.id}</code>", 
                reply_markup=builder_admin.as_markup()
            )
            
            await show_admin_panel(message, state)
            return
        
        if message.chat.id in await db.admin_view():
            from handlers.users.additional.admin import show_admin_panel

            await show_admin_panel(message, state)
            return
        
        if not await db.is_user(message.chat.id):
            await db.user_plus(message.chat.id)

        user_id = message.from_user.id
        is_registered = await db.is_user_registered(user_id)

        if is_registered:
            user = await db.get_user_by_telegram_id(user_id)
            lang = user['language']

            await state.clear()
            await state.update_data(language=lang, user_id=user['id'])

            # Status xabari
            status_text = format_verification_status(user['verification_status'], lang)

            if user['verification_status'] == 'approved':
                status_msg = get_text(lang, 'status_approved')
                # Faqat tasdiqlangan foydalanuvchilar uchun asosiy menyu
                await message.answer(
                    get_text(lang, 'welcome_registered',
                            fullname=user['fullname'],
                            client_code=user['client_code'],
                            phone=user['phone'],
                            status=status_text,
                            status_message=status_msg),
                    reply_markup=main_menu_keyboard(lang, await db.is_admin(user_id))
                )
            elif user['verification_status'] == 'rejected':
                status_msg = get_text(lang, 'status_rejected', reason=user['rejection_reason'] or "—")
                # Rad etilgan foydalanuvchilar uchun qayta ro'yxatdan o'tish
                await message.answer(
                    get_text(lang, 'welcome_registered',
                            fullname=user['fullname'],
                            client_code=user['client_code'],
                            phone=user['phone'],
                            status=status_text,
                            status_message=status_msg),
                    reply_markup=ReplyKeyboardRemove()
                )
                await message.answer("Iltimos, qayta ro'yxatdan o'ting.", reply_markup=welcome_keyboard(lang))
            else:
                status_msg = get_text(lang, 'status_pending')
                # Kutilayotgan foydalanuvchilar uchun faqat status
                await message.answer(
                    get_text(lang, 'welcome_registered',
                            fullname=user['fullname'],
                            client_code=user['client_code'],
                            phone=user['phone'],
                            status=status_text,
                            status_message=status_msg),
                    reply_markup=ReplyKeyboardRemove()
                )
        else:
            # Yangi foydalanuvchi
            data = await state.get_data()
            inactive_user = await db.get_user_by_telegram_id(user_id, active_only=False)
            if inactive_user:
                lang = inactive_user['language']
                await clear_state_keep_language(state, lang)
                bot_title = await bot.get_me()
                await message.answer(
                    get_text(lang, 'welcome_new', bot_name=bot_title.first_name),
                    reply_markup=welcome_keyboard(lang)
                )
                return

            # Agar til hali tanlanmagan bo'lsa, avval tilni so'raymiz
            if not data.get('language'):
                await state.clear()
                await message.answer(
                    "Iltimos, tilni tanlang / Пожалуйста, выберите язык:",
                    reply_markup=language_keyboard()
                )
                return

            lang = data.get('language', 'uz')
            await clear_state_keep_language(state, lang)
            bot_title = await bot.get_me()
            await message.answer(
                get_text(lang,  'welcome_new', bot_name=bot_title.first_name),
                reply_markup=welcome_keyboard(lang)
            )

@dp.callback_query(lambda c: c.data == 'check')
async def callback_query_handler(call: CallbackQuery) -> None:
    await call.answer()
    me = await bot.get_me()
    chat_id = call.message.chat.id
    
    if not await db.is_user(chat_id):
        await db.user_plus(chat_id)
    
