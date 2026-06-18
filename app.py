import middlewares, filters, handlers
import asyncio
import logging
import sys
from loader import dp, bot
from utils.sqlite_storage import SQLiteStorage
from middlewares.throttling import ThrottlingMiddleware
from middlewares.check_user import UserCheckMiddleware
from utils.notify_admins import on_startup_notify
from utils.backup_scheduler import start_daily_backup_scheduler
from utils.audit_log import audit_logger
from utils.set_bot_commands import set_default_commands
from data.Async_sqlDataBase import data_db as db

logger = logging.getLogger(__name__)

async def main():
    """Asosiy funksiya - bot va barcha background vazifalarini boshqaradi"""
    logger.info("Bot ishga tushmoqda...")

    # Database ni initialize qilish
    logger.info("Database initialize qilinyoqda...")
    try:
        await db.start()
        logger.info("✅ Database muvaffaqiyatli initialize qilindi")
    except Exception as e:
        logger.error(f"Database initialize qilishda xato: {e}")
        raise

    # Audit log ni initialize qilish
    try:
        await audit_logger.initialize()
        logger.info("✅ Audit logger muvaffaqiyatli initialize qilindi")
    except Exception as e:
        logger.error(f"Audit logger initialize qilishda xato: {e}")

    # Middleware larni ro'yxatdan o'tkazish
    dp.message.middleware.register(ThrottlingMiddleware())
    dp.update.middleware.register(UserCheckMiddleware())


    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook o'chirildi")

        # Bot command menyusini o'rnatish (/start, /help, ...)
        await set_default_commands()
        logger.info("Bot commandlar o'rnatildi")


        # Admin notifikasiyalarini yuborish
        await on_startup_notify()
        
        # Background vazifalarni ishga tushirish
        asyncio.create_task(start_daily_backup_scheduler())
        
        logger.info("Bot polling rejimda ishlamoqda...")

        # Asosiy polling loopini ishga tushirish
        await dp.start_polling(bot, skip_updates=True)

    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi")
    except Exception as e:
        logger.error(f"Asosiy bot xatosi: {e}", exc_info=True)
    finally:
        # Database connectionlarini yopish
        await db.close()
        await audit_logger.close()
        # FSM Storage ni yopish
        if isinstance(dp.storage, SQLiteStorage):
            await dp.storage.close()
        logger.info("Database connectionlari yopildi")

        # Bot sessionini yopish
        await bot.session.close()
        logger.info("Bot to'xtatildi")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi")
    except SystemExit:
        logger.info("Bot tizim tomonidan to'xtatildi")
    except Exception as e:
        logger.critical(f"Jiddiy xato: {e}", exc_info=True)