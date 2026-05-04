"""
main.py

в строке 441 можно поменять текст на любой другой, который будет отправляться пользователям при команде /ping

Запуск:
  pip install -r requirements.txt
  .env   # заполнить данными
  python main.py
"""

import asyncio
import os
import re
import random
import json
import glob

from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from telethon.errors import FloodWaitError

from config import load_config
from database import (
    init_db,
    # excluded
    db_add_excluded, db_remove_excluded, db_get_excluded_ids,
    db_get_excluded_list, db_is_excluded,
    # settings
    db_get_setting, db_set_setting, db_get_all_settings,
)

# ─────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ─────────────────────────────────────────────────────────────────────────────
config = load_config()

# Проверка обязательных параметров
assert config.API_ID,     " Укажи API_ID в .env"
assert config.API_HASH,   " Укажи API_HASH в .env"
assert config.BOT_TOKEN,  " Укажи BOT_TOKEN в .env"

# ─────────────────────────────────────────────────────────────────────────────
# Клиент Telethon
# ─────────────────────────────────────────────────────────────────────────────
client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)

# Словарь состояний: (chat_id, user_id) -> данные ожидания
waiting_states: dict[tuple, dict] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Проверка прав администратора
# ─────────────────────────────────────────────────────────────────────────────

async def is_admin(event) -> bool:
    """
    Возвращает True, если отправитель:
    - в списке ADMIN_IDS из конфига, ИЛИ
    - является администратором/создателем группы в Telegram.
    """
    uid = event.sender_id

    # Глобальные администраторы бота
    if uid in config.ADMIN_IDS:
        return True

    # Администраторы конкретной группы
    use_local = await db_get_setting('use_local_admins', 'true')
    if use_local == 'true':
        try:
            perms = await client.get_permissions(event.chat_id, uid)
            if perms.is_admin or perms.is_creator:
                return True
        except Exception:
            pass

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

async def get_target_user(event) -> User | None:
    """
    Определяет целевого пользователя из события:
    1. Ответ на сообщение (reply)
    2. @username или ID в аргументах команды
    """
    if event.is_reply:
        reply = await event.get_reply_message()
        if reply and reply.sender_id:
            try:
                return await client.get_entity(reply.sender_id)
            except Exception:
                pass

    args = event.message.text.split(maxsplit=1)
    if len(args) > 1:
        arg = args[1].strip()
        if arg:
            try:
                entity = await client.get_entity(arg)
                if isinstance(entity, User):
                    return entity
            except Exception:
                pass
    return None


def _mention_str(user: dict) -> str:
    """Формирует строку упоминания для пользователя (из словаря БД или объекта)."""
    if isinstance(user, dict):
        uid = user.get('user_id') or user.get('id')
        username = user.get('username', '')
        name = user.get('first_name', '') or f'id{uid}'
    else:
        uid = user.id
        username = getattr(user, 'username', '') or ''
        name = getattr(user, 'first_name', '') or f'id{uid}'

    if username:
        return f'@{username}'
    return f'[{name}](tg://user?id={uid})'


# ─────────────────────────────────────────────────────────────────────────────
# Функция отправки упоминаний (чат целиком)
# ─────────────────────────────────────────────────────────────────────────────

async def send_mentions(event, text: str = ''):
    """
    Получает список участников чата и отправляет упоминания
    чанками по 5 человек, пропуская исключённых и самого бота.
    """
    try:
        participants = await client.get_participants(event.chat_id)
    except Exception as e:
        return await event.reply(f'Не могу получить список участников: {e}')

    excluded_ids = await db_get_excluded_ids()
    bot_id = (await client.get_me()).id

    # Фильтруем: убираем бота и исключённых
    users = [u for u in participants if u.id != bot_id and u.id not in excluded_ids]

    if not users:
        return await event.reply('Нет пользователей для упоминания.')

    chunk_size = int(await db_get_setting('mention_chunk_size', '5'))
    delay_normal = float(await db_get_setting('mention_delay_normal', '1'))
    delay_chunk = float(await db_get_setting('mention_delay_chunk', '3'))
    chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]
    sent = 0

    for chunk in chunks:
        mentions = ' '.join(_mention_str(u) for u in chunk)
        msg = f'{text}\n{mentions}' if text else mentions
        buttons = [[Button.inline('🔕 Не получать пинг', b'mute_ping')],
                    [Button.inline('🔔 Получать пинг', b'unmute_ping')],
                ]

        try:
            await event.respond(msg, buttons=buttons, parse_mode='markdown')
            sent += 1
            await asyncio.sleep(delay_chunk if sent % 3 == 0 else delay_normal)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception as e:
            await event.reply(f'Ошибка при отправке: {e}')
            break

    await event.reply(f'✅ Упоминания отправлены ({sent} сообщений)')


# ─────────────────────────────────────────────────────────────────────────────
# /start и /help
# ─────────────────────────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r'^/start(@\w+)?$'))
async def cmd_start(event):
    text = (
        "🤖 **Многофункциональный бот**\n\n"

        "**📢 Упоминания:**\n"
        "`/mention` — упомянуть всех участников\n"
        "`/add_excluded` — добавить в исключения (reply / @username)\n"
        "`/remove_excluded` — убрать из исключений\n"
        "`/list_excluded` — список исключённых\n"
        "`/list_excluded_panel` — панель управления исключениями (кнопки)\n"
        "`/settings` — настройки функций\n\n"

        f"👑 Глобальные администраторы: {', '.join(map(str, config.ADMIN_IDS)) or 'не указаны'}"
    )
    await event.reply(text, parse_mode='markdown')


# ─────────────────────────────────────────────────────────────────────────────
# /mention
# ─────────────────────────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r'^/mention(@\w+)?$'))
async def cmd_mention(event):
    """Показывает кнопки выбора режима упоминания."""
    if event.is_private:
        return await event.reply('Команда работает только в группах.')
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    buttons = [
        [Button.inline('📢 Без текста', b'mention_no_text')],
        [Button.inline('✏️ С текстом',  b'mention_with_text')],
    ]
    await event.reply('Выберите режим упоминания:', buttons=buttons)


# ─────────────────────────────────────────────────────────────────────────────
# /list_excluded_panel — интерактивная панель управления исключениями
# ─────────────────────────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r'^/list_excluded_panel(@\w+)?$'))
async def cmd_excluded_panel(event):
    """
    Показывает всех участников чата в виде кнопок:
    🟢 зелёный — НЕ в исключениях (нажатие добавит в исключения)
    🔴 красный  — В исключениях (нажатие уберёт из исключений)
    """
    if event.is_private:
        return await event.reply('Команда работает только в группах.')
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    await _send_excluded_panel(event)


async def _send_excluded_panel(event, edit=False):
    """
    Формирует и отправляет (или редактирует) панель управления исключениями.
    edit=True — редактирует существующее сообщение (для callback).
    """

    try:
        participants = await client.get_participants(event.chat_id)
    except Exception as e:
        return await event.reply(f'Не могу получить список участников: {e}')

    bot_id = (await client.get_me()).id
    excluded_ids = await db_get_excluded_ids()

    # Фильтруем ботов и самого бота
    users = [u for u in participants if u.id != bot_id and not getattr(u, 'bot', False)]

    if not users:
        return await event.reply('Нет участников для отображения.')

    # Строим кнопки: по 2 в ряд
    buttons = []
    row = []
    for u in users:
        is_excl = u.id in excluded_ids
        name = u.first_name or u.username or f'id{u.id}'
        # Обрезаем длинные имена
        label = ('🔴 ' if is_excl else '🟢 ') + (name[:18] + '…' if len(name) > 18 else name)
        # Данные кнопки: excl_toggle:<user_id>
        row.append(Button.inline(label, f'excl_toggle:{u.id}'.encode()))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Кнопка закрытия
    buttons.append([Button.inline('✅ Закрыть', b'panel_close')])

    total = len(users)
    excl_count = sum(1 for u in users if u.id in excluded_ids)
    text = (
        f'👥 **Участники чата** ({total} чел.)\n'
        f'🔴 В исключениях: {excl_count} | 🟢 Активных: {total - excl_count}\n\n'
        'Нажмите на участника, чтобы добавить/убрать из исключений.'
    )

    if edit:
        try:
            await event.edit(text, buttons=buttons, parse_mode='markdown')
        except Exception:
            pass
    else:
        await event.reply(text, buttons=buttons, parse_mode='markdown')


# ─────────────────────────────────────────────────────────────────────────────
# Обработчик всех CallbackQuery (нажатий на кнопки)
# ─────────────────────────────────────────────────────────────────────────────

@client.on(events.CallbackQuery)
async def callback_handler(event):
    """Единый обработчик для всех inline-кнопок бота."""
    data = event.data  # bytes

    # ── Кнопка "Не получать пинг" — доступна ВСЕМ (без проверки админа) ──
    if data == b'mute_ping':
        try:
            user = await client.get_entity(event.sender_id)
            if await db_is_excluded(event.sender_id):
                await event.answer('⚠️ Вы уже в списке исключений!', alert=True)
            else:
                await db_add_excluded(event.sender_id, user.first_name or '', user.username or '')
                await event.answer('✅ Вы больше не будете получать пинги!', alert=True)
        except Exception as e:
            await event.answer(f'❌ Ошибка: {e}', alert=True)
        return
    
    if data == b'unmute_ping':
        try:
            user = await client.get_entity(event.sender_id)
            if not await db_is_excluded(event.sender_id):
                await event.answer('⚠️ Вы не в списке исключений!', alert=True)
            else:
                await db_remove_excluded(event.sender_id)
                await event.answer('✅ Вы снова будете получать пинги!', alert=True)
        except Exception as e:
            await event.answer(f'❌ Ошибка: {e}', alert=True)
        return

    # ── Проверка прав ──────────────────────────────────────────────────────
    if not await is_admin(event):
        return await event.answer('❌ Только для администраторов!', alert=True)

    await event.answer()  # убираем «часики» с кнопки

    # ── Упоминания: без текста ─────────────────────────────────────────────
    if data == b'mention_no_text':
        await event.edit('⏳ Отправляю упоминания...')
        await send_mentions(event)

    # ── Упоминания: с текстом — запрашиваем текст ─────────────────────────
    elif data == b'mention_with_text':
        waiting_states[(event.chat_id, event.sender_id)] = {'mode': 'mention_text'}
        await event.edit(
            '✏️ Отправьте текст, который будет добавлен к упоминаниям.\n'
            'Просто напишите сообщение в чат.'
        )

    # ── Панель исключений: переключить пользователя ────────────────────────
    elif data.startswith(b'excl_toggle:'):
        uid_str = data.split(b':')[1].decode()
        try:
            uid = int(uid_str)
        except ValueError:
            return

        if await db_is_excluded(uid):
            # Убираем из исключений
            await db_remove_excluded(uid)
        else:
            # Добавляем в исключения — получаем имя пользователя
            try:
                user = await client.get_entity(uid)
                await db_add_excluded(uid, user.first_name or '', user.username or '')
            except Exception:
                await db_add_excluded(uid, '', '')

        # Обновляем панель
        await _send_excluded_panel(event, edit=True)
	
     # ── Настройки: изменить текст /ping ────────────────────────────────────
    elif data == b'set_ping_text':
        waiting_states[(event.chat_id, event.sender_id)] = {'mode': 'set_ping_text'}
        await event.edit(
            '✏️ Отправьте новый текст для команды /ping.\n\n'
            'Просто напишите сообщение в чат.',
            buttons=[[Button.inline('❌ Отмена', b'settings_cancel')]]
        )

    # ── Настройки: переключить локальных админов ──────────────────────────
    elif data == b'toggle_local_admins':
        current = await db_get_setting('use_local_admins', 'true')
        new_value = 'false' if current == 'true' else 'true'
        await db_set_setting('use_local_admins', new_value)
        await _send_settings_panel(event, edit=True)

    # ── Настройки: задержка обычная ───────────────────────────────────────
    elif data == b'set_delay_normal':
        waiting_states[(event.chat_id, event.sender_id)] = {'mode': 'set_delay_normal'}
        await event.edit(
            '⏱ Отправьте обычную задержку между сообщениями (в секундах).\n\n'
            'Например: 1.5',
            buttons=[[Button.inline('❌ Отмена', b'settings_cancel')]]
        )

    # ── Настройки: задержка чанк ──────────────────────────────────────────
    elif data == b'set_delay_chunk':
        waiting_states[(event.chat_id, event.sender_id)] = {'mode': 'set_delay_chunk'}
        await event.edit(
            '⏱ Отправьте задержку после группы сообщений (в секундах).\n\n'
            'Например: 3',
            buttons=[[Button.inline('❌ Отмена', b'settings_cancel')]]
        )

    # ── Настройки: размер чанка ───────────────────────────────────────────
    elif data == b'set_chunk_size':
        waiting_states[(event.chat_id, event.sender_id)] = {'mode': 'set_chunk_size'}
        await event.edit(
            '📦 Отправьте размер чанка (сколько человек в одном сообщении).\n\n'
            'От 1 до 50. Например: 5',
            buttons=[[Button.inline('❌ Отмена', b'settings_cancel')]]
        )

    # ── Настройки: отмена ─────────────────────────────────────────────────
    elif data == b'settings_cancel':
        waiting_states.pop((event.chat_id, event.sender_id), None)
        await _send_settings_panel(event, edit=True)
    
    # ── Панель исключений: закрыть ─────────────────────────────────────────
    elif data == b'panel_close':
        try:
            await event.delete()
        except Exception:
            await event.edit('✅ Панель закрыта.')


# ─────────────────────────────────────────────────────────────────────────────
# Команды управления исключениями (текстовые)
# ─────────────────────────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r'^/add_excluded(@\w+)?(\s|$)'))
async def cmd_add_excluded(event):
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    target = await get_target_user(event)
    if not target:
        return await event.reply('Укажите пользователя: ответьте на его сообщение или передайте @username.')

    ok = await db_add_excluded(target.id, target.first_name or '', target.username or '')
    name = target.first_name or target.username or f'ID {target.id}'
    if ok:
        await event.reply(f'✅ {name} добавлен в исключения.')
    else:
        await event.reply(f'⚠️ {name} уже в исключениях.')


@client.on(events.NewMessage(pattern=r'^/remove_excluded(@\w+)?(\s|$)'))
async def cmd_remove_excluded(event):
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    target = await get_target_user(event)
    if not target:
        return await event.reply('Укажите пользователя: ответьте на его сообщение или передайте @username.')

    ok = await db_remove_excluded(target.id)
    name = target.first_name or target.username or f'ID {target.id}'
    if ok:
        await event.reply(f'✅ {name} удалён из исключений.')
    else:
        await event.reply(f'❌ {name} не найден в исключениях.')


@client.on(events.NewMessage(pattern=r'^/list_excluded(@\w+)?$'))
async def cmd_list_excluded(event):
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    lst = await db_get_excluded_list()
    if not lst:
        return await event.reply('Список исключений пуст.')

    lines = []
    for u in lst:
        name = u['first_name'] or u['username'] or f"ID {u['user_id']}"
        lines.append(f'• {name}')
    await event.reply('📋 **Исключённые пользователи:**\n' + '\n'.join(lines), parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'^/settings(@\w+)?$'))
async def cmd_settings(event):
    """Показывает панель управления настройками с кнопками."""
    if not await is_admin(event):
        return await event.reply('❌ Только для администраторов.')

    await _send_settings_panel(event)


async def _send_settings_panel(event, edit=False):
    """Формирует и отправляет панель настроек."""
    settings = await db_get_all_settings()
    
    ping_text = settings.get('ping_text', 'Не задан')
    ping_preview = ping_text[:50] + '...' if len(ping_text) > 50 else ping_text
    
    use_local = settings.get('use_local_admins', 'true')
    local_status = '✅ Вкл' if use_local == 'true' else '❌ Выкл'
    
    delay_normal = settings.get('mention_delay_normal', '1')
    delay_chunk = settings.get('mention_delay_chunk', '3')
    chunk_size = settings.get('mention_chunk_size', '5')
    
    text = (
        "⚙️ **Настройки бота**\n\n"
        f"📝 **Текст /ping:** {ping_preview}\n"
        f"👥 **Админы группы:** {local_status}\n"
        f"⏱ **Задержка каждое соо:** {delay_normal}с\n"
        f"⏱ **Задержка каждые 3 соо:** {delay_chunk}с\n"
        f"📦 **Кол-во пингов в соо:** {chunk_size} чел.\n"
    )
    
    buttons = [
        [Button.inline('📝 Изменить текст /ping', b'set_ping_text'),
        Button.inline('👥 Локальные админы: ВКЛ/ВЫКЛ', b'toggle_local_admins')],
        [Button.inline('⏱ Задержка обычная', b'set_delay_normal'),
        Button.inline('⏱ Задержка чанк', b'set_delay_chunk')],
        [Button.inline('📦 Размер чанка', b'set_chunk_size'),
        Button.inline('✅ Закрыть', b'panel_close')],
    ]
    
    if edit:
        try:
            await event.edit(text, buttons=buttons, parse_mode='markdown')
        except Exception:
            pass
    else:
        await event.reply(text, buttons=buttons, parse_mode='markdown')    
    
# ── Глобальный обработчик входящих сообщений (триггеры + состояния) ──────────


@client.on(events.NewMessage)
async def global_message_handler(event):
    """
    Обрабатывает все входящие сообщения:
    1. Проверяет состояния ожидания (mention_text и т.д.)
    """
    if getattr(event.sender, 'bot', False):
        return

    text = event.message.text
    if not text:
        return

    # ── Состояния ожидания ────────────────────────────────────────────────
    key = (event.chat_id, event.sender_id)
    if key in waiting_states and not text.startswith('/') and not text.startswith('!'):
        state = waiting_states.pop(key)

        if state['mode'] == 'mention_text':
            await event.reply(f'✅ Отправляю упоминания с текстом: «{text}»')
            await send_mentions(event, text)
            return


@client.on(events.NewMessage(pattern=r'^/ping(@\w+)?$'))
async def ping_command(event):
    text = await db_get_setting('ping_text', 
        'В течение Золотого рубежа мы будем каждый день пинговать вас...')

    buttons = [
        [Button.inline('🔕 Не получать пинг', b'mute_ping')],
        [Button.inline('🔔 Получать пинг', b'unmute_ping')],
    ]

    await event.reply(text, buttons=buttons)

# ─────────────────────────────────────────────────────────────────────────────
# Запуск бота
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Инициализирует БД, регистрирует обработчики и запускает бота."""
    # 1. Инициализируем базу данных
    await init_db()

    # 2. Запускаем клиента
    await client.start(bot_token=config.BOT_TOKEN)

    # 4. Информация о боте
    me = await client.get_me()
    print(f'🤖 Бот запущен: @{me.username}')
    print(f'👑 Администраторы: {config.ADMIN_IDS or "не указаны"}')
    print(f'📂 База данных: {config.DB_PATH}')
    print('─' * 40)

    # 5. Ждём до отключения
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
