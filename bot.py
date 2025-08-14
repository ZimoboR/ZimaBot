# bot.py
import asyncio
import json
import os
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
    except Exception as e:
        print(f"❌ Ошибка сохранения ID: {e}")


# === Скачивание медиа с повторами ===
async def download_media(msg: Message):
    for _ in range(3):
        try:
            return await asyncio.wait_for(msg.download(in_memory=True), timeout=60)
        except (asyncio.TimeoutError, FloodWait):
            await asyncio.sleep(2)
        except Exception:
            return None
    return None


# === Отправка с повторами при ошибках ===
async def send_with_retry(client, func, *args, **kwargs):
    for _ in range(3):
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait: ждём {wait} сек.")
            await asyncio.sleep(wait)
        except SlowmodeWait as e:
            wait = e.value
            print(f"⏳ Slowmode: ждём {wait} сек.")
            await asyncio.sleep(wait)
        except RPCError as e:
            print(f"❌ Ошибка отправки: {e}")
            break
        except Exception as e:
            print(f"❌ Неизвестная ошибка: {e}")
            break
        await asyncio.sleep(1)
    return None


# === Основной цикл копирования ===
async def clone_loop():
    global last_status
    last_id = await get_last_id()
    last_status = f"🟢 Мониторинг запущен. Последний ID: {last_id}"
    print(last_status)

    async with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as user_client:
        while monitoring:
            try:
                new_msgs = []
                async for msg in user_client.get_chat_history(DONOR_ID, limit=10):
                    if msg.id > last_id:
                        new_msgs.append(msg)
                    else:
                        break
                new_msgs = new_msgs[::-1]

                if new_msgs:
                    print(f"📥 Найдено {len(new_msgs)} новых сообщений")
                    for msg in new_msgs:
                        if msg.service:
                            continue

                        try:
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

                            last_id = msg.id
                            await save_last_id(last_id)
                            await bot.send_message(ADMIN_ID, f"✅ Скопировано сообщение #{msg.id}")

                        except Exception as e:
                            print(f"❌ Ошибка при копировании {msg.id}: {e}")

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"🚨 Ошибка в цикле: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

        last_status = "🔴 Остановлен"
        await bot.send_message(ADMIN_ID, "🛑 Мониторинг остановлен.")


# === Команды бота ===
@Client.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_monitoring(_, message: Message):
    global monitoring
    if not monitoring:
        monitoring = True
        asyncio.create_task(clone_loop())
        await message.reply("✅ Мониторинг запущен.")
    else:
        await message.reply("⚠️ Уже запущено.")


@Client.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_monitoring(_, message: Message):
    global monitoring
    monitoring = False
    await message.reply("🛑 Мониторинг остановлен.")


@Client.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(_, message: Message):
    await message.reply(f"📊 Текущий статус:\n{last_status}")


# === Запуск бота ===
async def main():
    global bot
    bot = Client(BOT_SESSION, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await bot.start()
    await bot.send_message(ADMIN_ID, "🟢 Бот запущен. Используй /start, /stop, /status")
    print("✅ Бот запущен. Управляй через Telegram.")

    # Держим бота в живых (аналог bot.idle())
    try:
        while True:
            await asyncio.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Бот остановлен.")
    finally:
        await bot.stop()


if __name__ == '__main__':
    asyncio.run(main())
