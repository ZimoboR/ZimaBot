# bot.py
import asyncio
import json
import os
# from http.server import HTTPServer, SimpleHTTPRequestHandler # Убираем веб-сервер
# import threading # Убираем threading для веб-сервера
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, SlowmodeWait, RPCError

# === Настройки из переменных окружения ===
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# === Настройки каналов ===
DONOR_ID = -1001876663463  # Канал-донор
MY_ID = -1002763227980     # Твой канал для копирования

# === Прочие настройки ===
CHECK_INTERVAL = 15         # Проверять каждые 15 секунд
STATE_FILE = "last_message.json"
SESSION_NAME = "cloner_user"
BOT_SESSION = "cloner_bot"

# === Глобальные переменные ===
monitoring = False
last_status = "🔴 Остановлен"


# === Функция: получить последний обработанный ID ===
async def get_last_id():
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            return data.get(str(DONOR_ID), 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


# === Функция: сохранить последний ID ===
async def save_last_id(msg_id: int):
    try:
        data = {}
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        data[str(DONOR_ID)] = msg_id
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f)
        print(f"💾 Сохранён ID: {msg_id}")
    except Exception as e:
        print(f"❌ Ошибка сохранения ID: {e}")


# === Скачивание медиа с повторами ===
async def download_media(msg: Message):
    for attempt in range(3):
        try:
            print(f"📥 Скачивание медиа (попытка {attempt + 1}) для сообщения {msg.id}")
            return await asyncio.wait_for(msg.download(in_memory=True), timeout=60)
        except asyncio.TimeoutError:
            print(f"⚠️ Таймаут скачивания медиа для сообщения {msg.id}")
        except FloodWait as e:
            print(f"⏳ FloodWait при скачивании: ждём {e.value} секунд")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"❌ Ошибка скачивания медиа для сообщения {msg.id}: {e}")
            break
        await asyncio.sleep(1)
    return None


# === Отправка с повторами при ошибках ===
async def send_with_retry(client, func, *args, **kwargs):
    for attempt in range(3):
        try:
            print(f"📤 Отправка сообщения (попытка {attempt + 1})")
            return await func(*args, **kwargs)
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait: ждём {wait} сек.")
            await asyncio.sleep(wait)
        except SlowmodeWait as e:
            wait = e.value
            print(f"⏳ Slowmode: ждём {wait} сек.")
        except RPCError as e:
            print(f"❌ Ошибка отправки: {e}")
            break
        except Exception as e:
            print(f"❌ Неизвестная ошибка отправки: {e}")
            break
        await asyncio.sleep(1)
    return None


# === Основной цикл копирования ===
async def clone_loop(bot_client):
    global last_status, monitoring
    print("🔄 Запуск цикла мониторинга...")
    last_id = await get_last_id()
    last_status = f"🟢 Мониторинг запущен. Последний ID: {last_id}"
    print(last_status)

    async with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as user_client:
        while monitoring:
            try:
                print("🔁 Проверка новых сообщений...")
                new_msgs = []
                # Получаем последние 10 сообщений
                async for msg in user_client.get_chat_history(DONOR_ID, limit=10):
                    if msg.id > last_id:
                        new_msgs.append(msg)
                    else:
                        break  # Сообщения идут по убыванию
                new_msgs = new_msgs[::-1] # От старых к новым

                if new_msgs:
                    print(f"📥 Найдено {len(new_msgs)} новых сообщений")
                    for msg in new_msgs:
                        if msg.service:  # Пропускаем служебные
                            print(f"⏭️ Пропущено служебное сообщение {msg.id}")
                            continue

                        try:
                            print(f"📤 Обработка сообщения {msg.id}")
                            if msg.video:
                                video = await download_media(msg)
                                if video:
                                    await send_with_retry(
                                        user_client, user_client.send_video,
                                        chat_id=MY_ID, video=video,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                            elif msg.photo:
                                photo = await download_media(msg)
                                if photo:
                                    await send_with_retry(
                                        user_client, user_client.send_photo,
                                        chat_id=MY_ID, photo=photo,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                            elif msg.document:
                                doc = await download_media(msg)
                                if doc:
                                    await send_with_retry(
                                        user_client, user_client.send_document,
                                        chat_id=MY_ID, document=doc,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                            elif msg.text:
                                await send_with_retry(
                                    user_client, user_client.send_message,
                                    chat_id=MY_ID, text=msg.text,
                                    parse_mode=ParseMode.HTML
                                )

                            # Обновляем ID
                            last_id = msg.id
                            await save_last_id(last_id)

                            # Уведомляем админа
                            # await bot_client.send_message(ADMIN_ID, f"✅ Скопировано сообщение #{msg.id}")

                        except Exception as e:
                            print(f"❌ Ошибка при копировании {msg.id}: {e}")

                else:
                     print("⏳ Нет новых сообщений")

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"🚨 Ошибка в цикле: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

        # После остановки
        last_status = "🔴 Остановлен"
        print("🛑 Мониторинг остановлен")
        # await bot_client.send_message(ADMIN_ID, "🛑 Мониторинг остановлен.") # Раскомментируй, если нужно


# === Запуск бота ===
async def main():
    print("🚀 Запуск Telegram-бота...")

    # Создаём экземпляр бота
    bot = Client(BOT_SESSION, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    # === Регистрируем обработчики команд здесь, после создания бота ===
    @bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
    async def start_monitoring_handler(client, message: Message):
        global monitoring
        user_id = message.from_user.id
        print(f"📥 Получена команда /start от {user_id}")
        if not monitoring:
            monitoring = True
            # Передаем экземпляр бота в clone_loop
            asyncio.create_task(clone_loop(client))
            await message.reply("✅ Мониторинг запущен.")
            print("🟢 Мониторинг запущен по команде /start")
        else:
            await message.reply("⚠️ Уже запущено.")

    @bot.on_message(filters.command("stop") & filters.user(ADMIN_ID))
    async def stop_monitoring_handler(client, message: Message):
        global monitoring
        user_id = message.from_user.id
        print(f"📥 Получена команда /stop от {user_id}")
        monitoring = False
        await message.reply("🛑 Мониторинг остановлен.")
        print("🔴 Мониторинг остановлен по команде /stop")

    @bot.on_message(filters.command("status") & filters.user(ADMIN_ID))
    async def status_handler(client, message: Message):
        user_id = message.from_user.id
        print(f"📥 Получена команда /status от {user_id}")
        await message.reply(f"📊 Текущий статус:\n{last_status}")
        print(f"📤 Отправлен статус: {last_status}")

    # Подключаемся к Telegram
    print("🔌 Подключение бота к Telegram...")
    await bot.start()
    print("✅ Бот подключён к Telegram")

    # Отправляем приветственное сообщение админу
    try:
        await bot.send_message(ADMIN_ID, "🟢 Бот запущен. Используй /start, /stop, /status")
        print("✉️ Приветственное сообщение отправлено админу")
    except Exception as e:
        print(f"⚠️ Не удалось отправить приветственное сообщение: {e}")

    print("✅ Основной цикл бота запущен. Ожидание команд...")

    # Держим бота в живых
    try:
        while True:
            await asyncio.sleep(10) # Уменьшаем sleep для более быстрой реакции
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Получен сигнал остановки.")
    finally:
        print("🧹 Остановка бота...")
        await bot.stop()
        print("✅ Бот остановлен.")


# === Точка входа ===
if __name__ == '__main__':
    print("--- Запуск приложения ---")
    asyncio.run(main())
    print("--- Приложение завершено ---")
