"""
database.py — работа с базой данных SQLite через aiosqlite.

Таблицы:
  excluded_users  — пользователи, исключённые из упоминаний
  replies         — кастомные ответы на триггеры
  groups          — группы пользователей
  group_members   — связь пользователь ↔ группа
  economy         — баланс пользователей (задел на будущее)
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

        await db.commit()
    print("✅ База данных инициализирована")


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

