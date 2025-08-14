# bot.py
import asyncio
import json
import os
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, RPCError, SlowmodeWait

# === Настройки из переменных окружения ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# === Настройки каналов ===
DONOR_ID = -1001876663463  # Канал-донор
MY_ID = -1002763227980     # Твой канал для копирования

# === Прочие настройки ===
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 60
SEND_TIMEOUT = 30
CHECK_INTERVAL = 15  # Проверять каждые 15 секунд
STATE_FILE = "last_message.json"
SESSION_NAME = "cloner_user"
BOT_SESSION = "cloner_bot"

# === Глобальные переменные ===
monitoring_task = None  # Ссылка на задачу мониторинга
last_status = "🔴 Остановлен"
bot_client = None  # Ссылка на клиента бота


# === Функция: получить последний обработанный ID ===
async def get_last_processed_id(donor_id: int) -> int:
    """Читает ID последнего обработанного сообщения из файла"""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(str(donor_id), 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


# === Функция: сохранить последний ID ===
async def save_last_processed_id(donor_id: int, msg_id: int):
    """Сохраняет ID последнего обработанного сообщения"""
    try:
        data = {}
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        data[str(donor_id)] = msg_id

        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Не удалось сохранить состояние: {e}")


# === Функция: получить новые сообщения ===
async def fetch_new_messages(client: Client, donor_id: int, last_id: int):
    """Получает сообщения новее last_id (в порядке от старых к новым)"""
    new_messages = []
    async for msg in client.get_chat_history(donor_id, limit=10):  # Смотрим последние 10
        if msg.id > last_id:
            new_messages.append(msg)
        else:
            break  # Сообщения идут по убыванию, значит дальше старые
    return new_messages[::-1]  # От старых к новым


# === Функция: скачать медиа ===
async def download_media(msg: Message):
    for attempt in range(MAX_RETRIES):
        try:
            print(f"📥 Скачивание медиа (попытка {attempt + 1}) для сообщения {msg.id}")
            return await asyncio.wait_for(msg.download(in_memory=True), timeout=DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"⚠️ Таймаут скачивания (попытка {attempt + 1})")
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait при скачивании: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue
        except RPCError as e:
            print(f"❌ Ошибка скачивания: {e}")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            break
        await asyncio.sleep(1)
    return None


# === Функция: отправить с повторами ===
async def send_with_retry(client: Client, func, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            print(f"📤 Отправка сообщения (попытка {attempt + 1})")
            return await asyncio.wait_for(func(*args, **kwargs), timeout=SEND_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"⚠️ Таймаут отправки (попытка {attempt + 1})")
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue
        except SlowmodeWait as e:
            wait = e.value
            print(f"⏳ Slowmode: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue
        except RPCError as e:
            print(f"❌ Ошибка отправки: {e}")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            break
        await asyncio.sleep(1)
    return None


# === Основной цикл копирования (в отдельной задаче) ===
async def monitoring_loop():
    global last_status
    async with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as user_client:
        last_id = await get_last_processed_id(DONOR_ID)
        last_status = f"🟢 Мониторинг запущен. Последний ID: {last_id}"
        print(last_status)
        # Отправляем уведомление админу о запуске
        if bot_client:
            try:
                await bot_client.send_message(ADMIN_ID, last_status)
            except:
                pass  # Игнорируем ошибки отправки уведомления

        while True:  # Цикл будет прерван, если monitoring_task отменён
            try:
                print("🔁 Проверка новых сообщений...")
                # Получаем новые сообщения
                new_msgs = await fetch_new_messages(user_client, DONOR_ID, last_id)
                if new_msgs:
                    print(f"📥 Найдено {len(new_msgs)} новых сообщений!")

                    for msg in new_msgs:
                        print(f"📦 Копируем сообщение {msg.id}")
                        try:
                            if msg.service:
                                print("⏭️ Служебное — пропущено")
                                continue

                            if msg.video:
                                video = await download_media(msg)
                                if video:
                                    await send_with_retry(
                                        user_client,
                                        user_client.send_video,
                                        chat_id=MY_ID,
                                        video=video,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                else:
                                    print("❌ Не удалось скачать видео")

                            elif msg.photo:
                                photo = await download_media(msg)
                                if photo:
                                    await send_with_retry(
                                        user_client,
                                        user_client.send_photo,
                                        chat_id=MY_ID,
                                        photo=photo,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                else:
                                    print("❌ Не удалось скачать фото")

                            elif msg.document:
                                doc = await download_media(msg)
                                if doc:
                                    await send_with_retry(
                                        user_client,
                                        user_client.send_document,
                                        chat_id=MY_ID,
                                        document=doc,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                else:
                                    print("❌ Не удалось скачать документ")

                            elif msg.text:
                                await send_with_retry(
                                    user_client,
                                    user_client.send_message,
                                    chat_id=MY_ID,
                                    text=msg.text,
                                    parse_mode=ParseMode.HTML
                                )

                            else:
                                print(f"⏭️ Пропущен тип: {msg.media or 'unknown'}")

                            # Обновляем последний ID
                            last_id = msg.id
                            await save_last_processed_id(DONOR_ID, last_id)

                        except Exception as e:
                            print(f"❌ Ошибка при копировании {msg.id}: {e}")

                    print("✅ Все новые сообщения скопированы.")
                else:
                    print(f"⏳ Нет новых сообщений. Проверка через {CHECK_INTERVAL} сек...")

                await asyncio.sleep(CHECK_INTERVAL)

            except asyncio.CancelledError:
                print("🛑 Задача мониторинга отменена.")
                last_status = "🔴 Остановлен (задача отменена)"
                break
            except Exception as e:
                print(f"🚨 Ошибка в цикле: {e}")
                last_status = f"🟡 Ошибка: {e}"
                await asyncio.sleep(CHECK_INTERVAL)  # Ждем перед повтором

        last_status = "🔴 Остановлен"
        print(last_status)
        # Отправляем уведомление админу об остановке
        if bot_client:
            try:
                await bot_client.send_message(ADMIN_ID, "🛑 Мониторинг остановлен.")
            except:
                pass


# === Команды бота ===
@Client.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_monitoring(client: Client, message: Message):
    global monitoring_task, last_status
    if monitoring_task is None or monitoring_task.done():
        monitoring_task = asyncio.create_task(monitoring_loop())
        await message.reply("✅ Мониторинг запущен.")
        print("🟢 Мониторинг запущен по команде /start")
    else:
        await message.reply("⚠️ Мониторинг уже запущен.")

@Client.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_monitoring(client: Client, message: Message):
    global monitoring_task, last_status
    if monitoring_task and not monitoring_task.done():
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
        monitoring_task = None
        await message.reply("🛑 Мониторинг остановлен.")
        print("🔴 Мониторинг остановлен по команде /stop")
    else:
        await message.reply("⚠️ Мониторинг не запущен.")

@Client.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client: Client, message: Message):
    await message.reply(f"📊 Текущий статус:\n{last_status}")
    print(f"📤 Отправлен статус: {last_status}")


# === Запуск бота ===
async def main():
    global bot_client
    print("🚀 Запуск Telegram-бота...")

    # Создаем клиента бота
    bot_client = Client(BOT_SESSION, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    # Запускаем бота
    await bot_client.start()
    print("✅ Бот запущен. Управляй через Telegram.")

    # Отправляем приветственное сообщение
    try:
        await bot_client.send_message(ADMIN_ID, "🟢 Бот запущен. Используй /start, /stop, /status")
    except Exception as e:
        print(f"⚠️ Не удалось отправить приветственное сообщение: {e}")

    # Держим бота в живых
    try:
        # Бесконечный цикл для удержания бота активным
        while True:
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        print("🛑 Бот остановлен пользователем.")
    finally:
        print("🧹 Остановка бота...")
        await bot_client.stop()
        print("✅ Бот остановлен.")


if __name__ == '__main__':
    asyncio.run(main())
