# bot.py
import asyncio
import json
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, SlowmodeWait, RPCError

# Импорт из переменных окружения (ниже заменим)
import os

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ============ Настройки ============
DONOR_ID = -1001876663463
MY_ID = -1002763227980
CHECK_INTERVAL = 15
STATE_FILE = "last_message.json"
SESSION_NAME = "cloner_user"
BOT_SESSION = "cloner_bot"

# ============ Глобальные переменные ============
monitoring = False
last_status = "Остановлен"
client: Client = None
bot: Client = None


# ============ Функции ============
async def get_last_id():
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            return data.get(str(DONOR_ID), 0)
    except:
        return 0


async def save_last_id(msg_id: int):
    try:
        data = {}
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
        except:
            pass
        data[str(DONOR_ID)] = msg_id
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"❌ Ошибка сохранения ID: {e}")


async def download_media(msg: Message):
    for _ in range(3):
        try:
            return await asyncio.wait_for(msg.download(in_memory=True), timeout=60)
        except (asyncio.TimeoutError, FloodWait):
            await asyncio.sleep(2)
        except Exception:
            return None
    return None


async def send_with_retry(client, func, *args, **kwargs):
    for _ in range(3):
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except SlowmodeWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            print(f"❌ Ошибка отправки: {e}")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            break
        await asyncio.sleep(1)
    return None


async def clone_loop():
    global last_status
    last_id = await get_last_id()
    last_status = f"🟢 Мониторинг запущен. Последний ID: {last_id}"

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
                    for msg in new_msgs:
                        if msg.service:
                            continue

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
                        await bot.send_message(
                            ADMIN_ID,
                            f"✅ Скопировано сообщение #{msg.id}"
                        )

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"🚨 Ошибка: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

    last_status = "🔴 Остановлен"
    await bot.send_message(ADMIN_ID, "🛑 Мониторинг остановлен.")


# ============ Команды бота ============
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
    await message.reply(f"📊 Статус:\n{last_status}")


# ============ Запуск бота ============
async def main():
    global bot
    bot = Client(BOT_SESSION, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await bot.start()
    await bot.send_message(ADMIN_ID, "🟢 Бот запущен. Используй /start, /stop, /status")
    print("Бот запущен. Управляй через Telegram.")
    await bot.idle()


if __name__ == '__main__':
    asyncio.run(main())