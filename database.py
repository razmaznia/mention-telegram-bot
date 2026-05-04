"""
database.py — работа с базой данных SQLite через aiosqlite.

Таблицы:
  excluded_users  — пользователи, исключённые из упоминаний
  settings - настройки бота
"""

import aiosqlite
from config import load_config

config = load_config()

# ─────────────────────────────────────────────────────────────────────────────
# Инициализация — создаём все таблицы при первом запуске
# ─────────────────────────────────────────────────────────────────────────────

async def init_db():
    """Создаёт базу данных и все таблицы, если они ещё не существуют."""
    async with aiosqlite.connect(config.DB_PATH) as db:

        # Таблица исключённых пользователей (не получают упоминания)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS excluded_users (
                user_id     INTEGER PRIMARY KEY,
                first_name  TEXT    DEFAULT '',
                username    TEXT    DEFAULT '',
                added_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        
         # Таблица настроек
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        ''')

        # Настройки по умолчанию
        defaults = {
            'ping_text': 'В течение Золотого рубежа мы будем каждый день пинговать вас с просьбой зайти в игру, если вы не из нашей гильдии нажмите на кнопку ниже, если ничего не происходит, попробуйте позже - бот оффлайн',
            'use_local_admins': 'true',
            'mention_delay_normal': '1',
            'mention_delay_chunk': '3',
            'mention_chunk_size': '5',
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v)
            )

        await db.commit()
    print("✅ База данных инициализирована")


# ─────────────────────────────────────────────────────────────────────────────
# Настройки бота (settings)
# ─────────────────────────────────────────────────────────────────────────────

async def db_get_setting(key: str, default: str = '') -> str:
    """Получить значение настройки по ключу."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            return row['value'] if row else default
    except Exception as e:
        print(f"❌ db_get_setting: {e}")
        return default


async def db_set_setting(key: str, value: str) -> bool:
    """Установить значение настройки."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                """INSERT OR REPLACE INTO settings (key, value, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                (key, value)
            )
            await db.commit()
            return db.total_changes > 0
    except Exception as e:
        print(f"❌ db_set_setting: {e}")
        return False


async def db_get_all_settings() -> dict:
    """Получить все настройки в виде словаря {key: value}."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT key, value FROM settings ORDER BY key")
            rows = await cursor.fetchall()
            return {row['key']: row['value'] for row in rows}
    except Exception as e:
        print(f"❌ db_get_all_settings: {e}")
        return {}


async def db_reset_setting(key: str) -> bool:
    """Сбросить настройку (удалить, будет использоваться значение по умолчанию)."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute("DELETE FROM settings WHERE key = ?", (key,))
            await db.commit()
            return db.total_changes > 0
    except Exception as e:
        print(f"❌ db_reset_setting: {e}")
        return False
    
# ─────────────────────────────────────────────────────────────────────────────
# Excluded users
# ─────────────────────────────────────────────────────────────────────────────

async def db_add_excluded(user_id: int, first_name: str, username: str) -> bool:
    """Добавляет пользователя в список исключений. Возвращает False, если уже есть."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO excluded_users (user_id, first_name, username) VALUES (?,?,?)",
                (user_id, first_name, username)
            )
            await db.commit()
            return db.total_changes > 0
    except Exception as e:
        print(f"❌ db_add_excluded: {e}")
        return False


async def db_remove_excluded(user_id: int) -> bool:
    """Удаляет пользователя из исключений."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute("DELETE FROM excluded_users WHERE user_id=?", (user_id,))
            await db.commit()
            return db.total_changes > 0
    except Exception as e:
        print(f"❌ db_remove_excluded: {e}")
        return False


async def db_get_excluded_ids() -> set[int]:
    """Возвращает множество ID исключённых пользователей."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            async with db.execute("SELECT user_id FROM excluded_users") as cur:
                rows = await cur.fetchall()
                return {r[0] for r in rows}
    except Exception as e:
        print(f"❌ db_get_excluded_ids: {e}")
        return set()


async def db_get_excluded_list() -> list[dict]:
    """Возвращает список исключённых пользователей с именами."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id, first_name, username FROM excluded_users ORDER BY first_name"
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        print(f"❌ db_get_excluded_list: {e}")
        return []


async def db_is_excluded(user_id: int) -> bool:
    """Проверяет, находится ли пользователь в исключениях."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM excluded_users WHERE user_id=?", (user_id,)
            ) as cur:
                return await cur.fetchone() is not None
    except Exception as e:
        print(f"❌ db_is_excluded: {e}")
        return False

