import logging
from aiogram.fsm.context         import FSMContext
from data.Async_sqlDataBase      import data_db as db
from states.all_states           import for_admin
from loader                      import dp, bot
from keyboards.inline.admin_page import builder_admin, cancel_post_btn
from aiogram.types               import ContentType, Message, ChatMemberAdministrator, ChatMemberOwner

logger = logging.getLogger(__name__)

 
async def is_bot_admin(msg) -> bool:
    bot_info = await bot.get_me()
    try:
        chatid = await bot.get_chat(msg)
        chat_id = chatid.id
        member = await bot.get_chat_member(chat_id, bot_info.id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except Exception as e:
        logger.warning(f"Bot admin tekshiruvida xatolik: {e}")
        return False

@dp.message(for_admin.for_channel_add)
async def kanal_qoshish(message: Message, state: FSMContext):
    msg = message.text
    user_id = message.chat.id
    if (message.content_type == ContentType.TEXT):
        if msg == "/null":
            await message.delete()
            await state.clear()
            await message.answer(text = f"{message.chat.first_name} -- <b>⚜️Admin aka⚜️</b> Assalom-u alaykum Bot xizmatingizda!", reply_markup = builder_admin.as_markup())
        if not(msg.lower().startswith("https://") or msg.lower().startswith("http://") or msg.lower().startswith("@") or msg.isdigit() or msg.lower().startswith("t.me/")):
            await message.reply(text = "Siz kanalning 🔗 <b>Havolasi yoki 🆔 raqam</b>ini kiritishingiz kerak!\n<i>❗️ Qayta kiriting:</i> /null", reply_markup = cancel_post_btn.as_markup())
        else:
            if msg.startswith("https://t.me/"):
                msg = msg.replace("https://t.me/", "@")
            elif msg.startswith("http://t.me/"):
                msg = msg.replace("http://t.me/", "@")
            elif msg.startswith("t.me/"):
                msg = msg.replace("t.me/", "@")

        if await is_bot_admin(msg):
            await state.clear()
            kanal = await bot.get_chat(msg)
            channel_id = kanal.id
            if await db.is_channel(channel_id):
                await message.reply(text = f"🤒 <a href='{kanal.invite_link}'>{kanal.title}</a> kanali allaqachon qo'shilgan", reply_markup = builder_admin.as_markup())
                return
            await db.channel_plus(channel_id, user_id)
            await message.reply(text = f"🥳 <b>Tabriklayman siz ushbu kanalni qo'shdingiz!</b>", reply_markup = builder_admin.as_markup())
        else:
            await message.reply("⏸️ Bot bu <b>Kanalga Qo'shilmagan yoki Administrator</b> emas\n", reply_markup = builder_admin.as_markup())
            await state.clear()
    else:
        await message.reply("🌶️ Noto'g'ri formatda kiritildi!\n💢 <b>Kanal havolasi yoki ID raqamlarini kiriting: </b>/null", reply_markup = cancel_post_btn.as_markup())


