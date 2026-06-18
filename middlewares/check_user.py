from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardButton, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loader import bot
from data.Async_sqlDataBase import data_db as db
import logging

DEFAULT_RATE_LIMIT = 0.1
logger = logging.getLogger(__name__)

class UserCheckMiddleware(BaseMiddleware):
    def __init__(self, limit=DEFAULT_RATE_LIMIT, key_prefix='antiflood_'):
        self.rate_limit = limit
        self.prefix = key_prefix
        super(UserCheckMiddleware, self).__init__()

    async def __call__(self, handler, event: Update, data: dict):
        # Majburiy obuna o'chirilgan bo'lsa — o'tkazib yuborish
        if not await db.status_force():
            return await handler(event, data)
        
        # Message yoki callback_query dan chat type va user_id olish
        message = event.message if event.message else None
        callback = event.callback_query if hasattr(event, 'callback_query') and event.callback_query else None
        
        # Agar na message, na callback bo'lsa — o'tkazish (inline_query, etc.)
        if not message and not callback:
            return await handler(event, data)
        
        # Chat type tekshiruvi — faqat private chatda ishlaydi
        if message and message.chat.type != 'private':
            return await handler(event, data)
        if callback and callback.message and callback.message.chat.type != 'private':
            return await handler(event, data)
        
        # User ID olish
        if message:
            user_id = message.from_user.id
        elif callback:
            user_id = callback.from_user.id
        else:
            return await handler(event, data)
        force = False
        buttons = []

        for x in await db.majburiy_subs_view():
            kanals = await bot.get_chat(x)
            try:
                res = await bot.get_chat_member(chat_id=x, user_id=user_id)
            except Exception:
                continue

            if res.status not in ['member', 'administrator', 'creator']:
                buttons.append(InlineKeyboardButton(text=f"{kanals.title}", url=f"{await kanals.export_invite_link()}"))
                force = True

        if force:
            builder = InlineKeyboardBuilder()
            builder.add(*buttons)
            builder.add(InlineKeyboardButton(text="Tasdiqlash ✅", callback_data="check"))
            builder.adjust(1)

            if await db.is_user(user_id):
                await db.del_user(user_id)

            await bot.send_message(
                chat_id=user_id,
                text="‼️ Bot to'liq ishlashi uchun kanallarga obuna bo'ling!",
                reply_markup=builder.as_markup()
            )
        else:
            return await handler(event, data)
