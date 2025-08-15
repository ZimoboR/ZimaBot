import asyncio
import json
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError, SlowmodeWait
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from keys import API_ID, API_HASH

# Конфигурация
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 60
SEND_TIMEOUT = 30
CHECK_INTERVAL = 120  # Проверять каждые 30 секунд
STATE_FILE = "last_message.json"  # Файл для сохранения последнего ID

async def get_last_processed_id(donor_id: int) -> int:
    """Читает ID последнего обработанного сообщения из файла"""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(str(donor_id), 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


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


async def fetch_new_messages(client: Client, donor_id: int, last_id: int):
    """Получает сообщения новее last_id (в порядке от старых к новым)"""
    new_messages = []
    async for msg in client.get_chat_history(donor_id, limit=10):  # Смотрим последние 10
        if msg.id > last_id:
            new_messages.append(msg)
        else:
            break  # Сообщения идут по убыванию, значит дальше старые
    return new_messages[::-1]  # От старых к новым


async def download_media(msg: Message):
    for attempt in range(MAX_RETRIES):
        try:
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


async def send_with_retry(client: Client, func, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
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


async def clone_new_messages(donor_channel_id: int, my_channel_id: int):
    async with Client('my_session', api_id=API_ID, api_hash=API_HASH) as client:
        print("🔄 Запуск мониторинга новых сообщений...")

        # Загружаем последний обработанный ID
        last_id = await get_last_processed_id(donor_channel_id)
        print(f"🟢 Последний ID: {last_id}. Ожидание новых сообщений...")

        while True:
            try:
                # Получаем новые сообщения
                new_msgs = await fetch_new_messages(client, donor_channel_id, last_id)
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
                                        client,
                                        client.send_video,
                                        chat_id=my_channel_id,
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
                                        client,
                                        client.send_photo,
                                        chat_id=my_channel_id,
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
                                        client,
                                        client.send_document,
                                        chat_id=my_channel_id,
                                        document=doc,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                else:
                                    print("❌ Не удалось скачать документ")

                            elif msg.text:
                                await send_with_retry(
                                    client,
                                    client.send_message,
                                    chat_id=my_channel_id,
                                    text=msg.text,
                                    parse_mode=ParseMode.HTML
                                )

                            else:
                                print(f"⏭️ Пропущен тип: {msg.media or 'unknown'}")

                            # Обновляем последний ID
                            last_id = msg.id
                            await save_last_processed_id(donor_channel_id, last_id)

                        except Exception as e:
                            print(f"❌ Ошибка при копировании {msg.id}: {e}")

                    print("✅ Все новые сообщения скопированы.")
                else:
                    print(f"⏳ Нет новых сообщений. Проверка через {CHECK_INTERVAL} сек...")

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"🚨 Ошибка в цикле: {e}")
                await asyncio.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    DONOR_ID = -1001876663463
    MY_ID = -1002763227980
    asyncio.run(clone_new_messages(DONOR_ID, MY_ID))
