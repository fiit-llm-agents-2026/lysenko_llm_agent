"""Telegram long-polling door: every chat is a thread in the same API checkpointer."""

import asyncio
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TELEGRAM_LIMIT = 4096
HTTP: aiohttp.ClientSession | None = None

dp = Dispatcher()


def split_text(text: str) -> list[str]:
    return [text[at:at + TELEGRAM_LIMIT] for at in range(0, len(text), TELEGRAM_LIMIT)] or [""]


def clean(text: str) -> str:
    return text.replace("**", "").replace("__", "").replace("`", "")


def plain_text(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = [clean(cell.strip()) for cell in stripped.strip("|").split("|")]
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            lines.append(" · ".join(cell for cell in cells if cell))
            continue
        if stripped.startswith("#"):
            line = stripped.lstrip("#").strip()
        lines.append(clean(line))
    return "\n".join(lines)


async def data_events(reply: aiohttp.ClientResponse):
    event: list[str] = []
    async for raw in reply.content:
        line = raw.decode(errors="replace").rstrip("\r\n")
        if not line:
            if event:
                yield "\n".join(event)
                event = []
            continue
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:")
        if data.startswith(" "):
            data = data[1:]
        event.append(data)
    if event:
        yield "\n".join(event)


async def ask_api(session: aiohttp.ClientSession, chat_id: int, user_id: int,
                  text: str) -> str:
    url = f"{API_URL}/chat/{chat_id}"
    timeout = aiohttp.ClientTimeout(total=300, sock_read=300)
    headers = {"X-Client": "telegram", "X-User-Id": str(user_id)}
    async with session.post(url, json={"text": text}, timeout=timeout,
                            headers=headers) as reply:
        reply.raise_for_status()
        parts: list[str] = []
        async for data in data_events(reply):
            if data == "[DONE]":
                break
            if data.startswith("[ERROR]"):
                raise RuntimeError(data)
            parts.append(data)
    return plain_text("".join(parts).strip())


@dp.message()
async def on_message(message: Message) -> None:
    if HTTP is None or not message.text:
        return
    if message.text == "/start":
        await message.answer("Спросите про спецкурсы: темы, места, расписание, запись.")
        return
    user_id = message.from_user.id if message.from_user else message.chat.id
    print(f"[tg] chat={message.chat.id} user={user_id} in={message.text}", flush=True)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await ask_api(HTTP, message.chat.id, user_id, message.text)
    except Exception as error:
        await message.answer(f"Сервис недоступен: {type(error).__name__}")
        return
    print(f"[tg] chat={message.chat.id} out={answer}", flush=True)
    for chunk in split_text(answer or "Empty reply"):
        await message.answer(chunk)


async def main() -> None:
    global HTTP
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    bot = Bot(token=token)
    me = await bot.get_me()
    print(f"bot: @{me.username} | api: {API_URL}", flush=True)
    async with aiohttp.ClientSession() as session:
        HTTP = session
        try:
            await dp.start_polling(bot)
        finally:
            HTTP = None
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
