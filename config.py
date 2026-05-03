"""
config.py — загрузка конфигурации из файла .env
Все чувствительные данные хранятся в .env, не в коде.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()


class Config:
    # ── Telegram API ──────────────────────────────────────────────────────────
    # Получить на https://my.telegram.org → API development tools
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")

    # Токен бота — получить у @BotFather
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # ── Администраторы бота (Telegram user ID) ────────────────────────────────
    # Перечисляем через запятую в .env: ADMIN_IDS=123456,789012
    ADMIN_IDS: list[int] = [
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip().isdigit()
    ]

    # ── Пути к файлам ─────────────────────────────────────────────────────────
    DB_PATH: str = os.getenv("DB_PATH", "bot.db")
    SESSION_NAME: str = os.getenv("SESSION_NAME", "bot_session")


def load_config() -> Config:
    """Возвращает объект конфигурации. Используется во всех модулях."""
    return Config()
