import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram.types import FSInputFile
from data.Async_sqlDataBase import data_db as db
from loader import bot

logger = logging.getLogger(__name__)

async def send_daily_backup():
    """Bot egasiga kunlik backupni yuborish"""
    try:
        # Bot egasini aniqlash
        admin_id = await db.owner_view()
        if not admin_id:
            logger.warning("Daily Backup: Bot egasi (owner) topilmadi, backup yuborilmadi.")
            return

        # Checkpoint yaratish
        success, msg, backup_path = await db.create_full_checkpoint()
        
        if success and backup_path and os.path.exists(backup_path):
            try:
                # Faylni yuborish
                # Fayl nomiga sana qo'shamiz
                date_str = datetime.now().strftime("%Y-%m-%d")
                new_filename = f"backup_{date_str}.sqlite3"
                
                document = FSInputFile(path=backup_path, filename=new_filename)
                
                await bot.send_document(
                    chat_id=admin_id,
                    document=document,
                    caption=f"📅 <b>Kunlik Avtomatik Backup</b>\n\n{msg}"
                )
                logger.info(f"Daily backup sent to admin: {admin_id}")
                
            except Exception as e:
                logger.error(f"Failed to send backup to admin: {e}")
            finally:
                # Vaqtinchalik faylni o'chirish
                if os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except:
                        pass
        else:
            logger.error(f"Daily Backup failed: {msg}")

    except Exception as e:
        logger.error(f"Error in send_daily_backup: {e}")

async def start_daily_backup_scheduler():
    """Har kuni soat 00:00 da ishga tushadigan scheduler"""
    logger.info("Daily backup scheduler is initializing...")
    
    while True:
        try:
            now = datetime.now()
            # Keyingi kun 00:00 ni hisoblash (yoki istalgan vaqt, masalan 03:00)
            # Hozircha User "har 1 kunda" degani uchun tun yarmiga qo'yamiz.
            tomorrow = now + timedelta(days=1)
            next_run = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Qolgan vaqtni hisoblash (sekundlarda)
            sleep_duration = (next_run - now).total_seconds()
            
            logger.info(f"Next automated backup scheduled for {next_run} (in {sleep_duration:.2f} seconds)")
            
            # Kutish
            await asyncio.sleep(sleep_duration)
            
            # Backup jarayonini boshlash
            await send_daily_backup()
            
            # Qayta ishga tushib ketmasligi uchun biroz kutish
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("Backup scheduler stopped")
            break
        except Exception as e:
            logger.error(f"Error in backup scheduler loop: {e}")
            # Xatolik bo'lsa 5 daqiqa kutib qayta urinib ko'rish
            await asyncio.sleep(300)
