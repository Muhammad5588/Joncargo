from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from data import config
import importlib.util as _ilu, os as _os

# utils/__init__.py da circular import bo'lmasligi uchun
# SQLiteStorage ni to'g'ridan-to'g'ri fayldan yuklaymiz
_spec = _ilu.spec_from_file_location(
    "sqlite_storage",
    _os.path.join(_os.path.dirname(__file__), "utils", "sqlite_storage.py"),
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SQLiteStorage = _mod.SQLiteStorage

bot = Bot(
    token=config.TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = SQLiteStorage(db_path="data/fsm_storage.sqlite3")
dp = Dispatcher(storage=storage)