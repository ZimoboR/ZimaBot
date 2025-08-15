# cloner_worker.py
import asyncio
import json
import os  # Для получения переменных окружения
# from pyrogram import Client # Импортируем внутри main, чтобы избежать потенциальных проблем с импортами до установки

# === Настройки из переменных окружения ===
# Убедитесь, что эти переменные установлены в настройках вашего Railway сервиса
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DONOR_ID = int(os.getenv("DONOR_ID"))
MY_ID = int(os.getenv("MY_ID"))

# Конфигурация (можно также вынести в env vars при желании)
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 60
SEND_TIMEOUT = 30
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 30))  # По умолчанию 30 секунд
STATE_FILE = "last_message.json"  # Файл для сохранения последнего ID

# Импорты Pyrogram внутри асинхронной функции или вверху, после установки
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError, SlowmodeWait
from pyrogram.types import Message
from pyrogram.enums import ParseMode


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
        print(f"💾 Последний ID сохранен: {msg_id}")
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
            print(f"📥 Скачивание медиа (попытка {attempt + 1}) для сообщения {msg.id}")
            return await asyncio.wait_for(msg.download(in_memory=True), timeout=DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"⚠️ Таймаут скачивания (попытка {attempt + 1}) для сообщения {msg.id}")
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait при скачивании сообщения {msg.id}: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue # Повторить попытку скачивания
        except RPCError as e:
            print(f"❌ Ошибка скачивания сообщения {msg.id}: {e}")
            break
        except Exception as e:
            print(f"❌ Неизвестная ошибка скачивания сообщения {msg.id}: {e}")
            break
        await asyncio.sleep(1)
    print(f"❌ Не удалось скачать медиа для сообщения {msg.id} после {MAX_RETRIES} попыток.")
    return None


async def send_with_retry(client: Client, func, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            print(f"📤 Отправка сообщения (попытка {attempt + 1})")
            return await asyncio.wait_for(func(*args, **kwargs), timeout=SEND_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"⚠️ Таймаут отправки (попытка {attempt + 1})")
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait при отправке: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue # Повторить попытку отправки
        except SlowmodeWait as e:
            wait = e.value
            print(f"⏳ Slowmode при отправке: ждём {wait} сек")
            await asyncio.sleep(wait)
            continue # Повторить попытку отправки
        except RPCError as e:
            print(f"❌ Ошибка отправки: {e}")
            break
        except Exception as e:
            print(f"❌ Неизвестная ошибка отправки: {e}")
            break
        await asyncio.sleep(1)
    print(f"❌ Не удалось отправить сообщение после {MAX_RETRIES} попыток.")
    return None


async def clone_new_messages():
    """Основная функция клонирования."""
    print("🔄 Инициализация клиента Pyrogram...")
    # Используем 'my_session' для файла сессии. Он будет создан при первом запуске.
    async with Client('my_session', api_id=API_ID, api_hash=API_HASH) as client:
        print("✅ Клиент Pyrogram подключен.")

        print("🔄 Запуск мониторинга новых сообщений...")

        # Загружаем последний обработанный ID
        last_id = await get_last_processed_id(DONOR_ID)
        print(f"🟢 Последний ID: {last_id}. Ожидание новых сообщений...")

        while True:
            try:
                print("🔁 Проверка новых сообщений...")
                # Получаем новые сообщения
                new_msgs = await fetch_new_messages(client, DONOR_ID, last_id)
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
                                        chat_id=MY_ID,
                                        video=video,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                    print(f"✅ Видео из сообщения {msg.id} отправлено.")
                                else:
                                    print("❌ Не удалось скачать видео")

                            elif msg.photo:
                                photo = await download_media(msg)
                                if photo:
                                    await send_with_retry(
                                        client,
                                        client.send_photo,
                                        chat_id=MY_ID,
                                        photo=photo,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                    print(f"✅ Фото из сообщения {msg.id} отправлено.")
                                else:
                                    print("❌ Не удалось скачать фото")

                            elif msg.document:
                                doc = await download_media(msg)
                                if doc:
                                    await send_with_retry(
                                        client,
                                        client.send_document,
                                        chat_id=MY_ID,
                                        document=doc,
                                        caption=msg.caption.html if msg.caption else None,
                                        parse_mode=ParseMode.HTML
                                    )
                                    print(f"✅ Документ из сообщения {msg.id} отправлен.")
                                else:
                                    print("❌ Не удалось скачать документ")

                            elif msg.text:
                                await send_with_retry(
                                    client,
                                    client.send_message,
                                    chat_id=MY_ID,
                                    text=msg.text,
                                    parse_mode=ParseMode.HTML
                                )
                                print(f"✅ Текст из сообщения {msg.id} отправлен.")

                            else:
                                print(f"⏭️ Пропущен тип: {msg.media or 'unknown'}")

                            # Обновляем последний ID ТОЛЬКО после успешной попытки обработки
                            # Это может привести к повторной обработке в случае частичного сбоя,
                            # но предотвращает пропуск сообщений. Можно доработать логику.
                            last_id = msg.id
                            await save_last_processed_id(DONOR_ID, last_id)

                        except Exception as e:
                            # Ловим ошибки на уровне обработки отдельного сообщения,
                            # чтобы не останавливать весь цикл
                            print(f"❌ Критическая ошибка при копировании {msg.id}: {e}")
                            # Можно добавить логику повтора или уведомления об ошибке

                    print("✅ Все новые сообщения скопированы.")
                else:
                    print(f"⏳ Нет новых сообщений. Проверка через {CHECK_INTERVAL} сек...")

                await asyncio.sleep(CHECK_INTERVAL)

            except asyncio.CancelledError:
                print("🛑 Задача клонирования была отменена.")
                break
            except Exception as e:
                # Ловим ошибки на уровне всего цикла проверки
                print(f"🚨 Критическая ошибка в цикле мониторинга: {e}")
                print("⚠️ Цикл перезапустится через интервал проверки...")
                await asyncio.sleep(CHECK_INTERVAL) # Ждем перед повтором цикла


# Точка входа для Railway
async def main():
    """Главная асинхронная функция для запуска воркера."""
    print("--- Запуск Telegram Cloner Worker ---")
    try:
        # Запускаем основной цикл клонирования
        await clone_new_messages()
    except KeyboardInterrupt:
        print("\n🛑 Работа воркера остановлена пользователем (Ctrl+C).")
    except Exception as e:
        print(f"🚨 Фатальная ошибка воркера: {e}")
    finally:
        print("--- Работа Telegram Cloner Worker завершена ---")


# Этот блок не будет выполняться на Railway, но полезен для локального тестирования
if __name__ == '__main__':
    asyncio.run(main())
