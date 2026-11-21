# Lysenko LLM agent

Ассистент по спецкурсам университета: ищет спецкурс, показывает расписание и свободные места, записывает студента. Каталог курсов фейковый и хранится в памяти.

## Запуск

```
cp .env.example .env
uv sync
uv run python run.py "What course can I take just to relax? Enroll me as Sasha."
uv run python run.py --thread drill "What course did I enroll in?"
uv run python run.py --thread visit-2 --user u-sasha "Morning! Anything on the board I would like?"
uv run python run.py --mermaid
```

## Память

Краткосрочная — по разговору: `--thread NAME` (по умолчанию `desk`). Тред хранится в `assistant.db` через `SqliteSaver` и переживает перезапуск процесса. Файл в `.gitignore`; чтобы всё забыть, удалите его. Когда в треде больше 20 сообщений, хук `summarize` (`after_agent`) сворачивает старые ходы в поле `summary` и удаляет их через `RemoveMessage`. Summary попадает в системный промпт через `dynamic_prompt`.

Долгосрочная — по человеку: `--user NAME` (по умолчанию `guest`), хранится в `memory.db` через `SqliteStore` (`--store memory` — стор в RAM, для контрольных прогонов). Два писателя: хук `patch_profile` после каждого хода патчит trustcall-экстрактором профиль студента (`Profile`: имя, программа, интересы, ограничения, namespace `("profiles", user_id)`), а агент в середине хода сам сохраняет факты тулами `save_memory` / `search_memories` (namespace `("memories", user_id)`). Профиль попадает в системный промпт строкой `Student card`. Разбор обоих писателей и диалогов — в `runs/session-05.md`.

Нагрузочный тест: `uv run python load_test.py` дважды прогоняет один и тот же 50-ходовой диалог (full buffer и суммаризация) и печатает токены по ходам. Результаты — в `runs/session-04.md`.

## Подтверждение и стриминг

`spec_course_enroll` — единственный инструмент, меняющий состояние, поэтому в интерактивном клиенте он закрыт `HumanInTheLoopMiddleware`: агент паркует ход в чекпоинтере и ждёт решения человека. Батчевые прогоны (`run.py`, `load_test.py`) остаются без гейта.

```
uv run python chat.py --thread demo --user u-sasha --store none
```

`chat.py` стримит токены (`stream_mode=["messages", "updates"]`), на паузе спрашивает `approve / edit / reject / respond` и продолжает через `Command(resume=...)`. Пауза переживает перезапуск процесса: `SqliteSaver` держит её в `assistant.db`, клиент подхватывает её при старте.

```
uv run python fork.py --thread demo --list
uv run python fork.py --thread demo --store none --at <checkpoint_id> --decision approve
uv run python fork.py --thread demo --store none --at <checkpoint_id> --decision reject
```

`fork.py` проигрывает тред от указанного чекпоинта: два запуска с разными решениями оставляют в истории две ветки одного диалога. Разбор — в `runs/session-06.md`.

## Langfuse

`docker-compose.yml` — upstream Langfuse v3.224.0, `docker-compose.override.yml` создаёт проект из ключей в `.env`, подменяет образ minio (`cgr.dev` недоступен) и убирает проброс порта postgres на хост.

```
docker compose up -d
```

UI: http://localhost:3000. Если в `.env` заданы ключи Langfuse, каждый запуск `run.py` пишет трейс.

Трейсинг общий для всех входов: `run.py`, `load_test.py`, `chat.py` и `fork.py` берут handler из `new_trace_handler()`, а metadata — из `trace_metadata()`: `langfuse_session_id` равен треду, `langfuse_user_id` — `LANGFUSE_USER_ID` (по умолчанию `sany1111`), тег `session-07`. Так один диалог собирается в одну сессию, а прогоны фильтруются по тегу.

Системный промпт живёт в prompt management:

```
uv run python run.py --publish-prompt
```

Команда публикует `SYSTEM` как `special-courses-desk` с меткой `production`. При старте `run.py` получает промпт по этой метке, а локальная строка остаётся fallback'ом, если Langfuse недоступен. Версия промпта привязывается к генерациям через `langfuse_prompt`.

Цена `deepseek/deepseek-v4.1-flash` задана в Langfuse (`$0.15/1M` input, `$0.60/1M` output), поэтому в трейсах считается `totalCost`; cache-read отдельно не тарифицирован.

Тест узла без инструментов:

```
uv run pytest -q
```

Разбор трейса, цены и узлов — в `runs/session-07.md`.

## Деплой

`service.py` — FastAPI-обёртка графа: `POST /chat/{thread_id}` отдаёт SSE, `GET /health` показывает выбранную ветку. `bot.py` — aiogram long polling; бот ходит в API, поэтому Telegram и веб-клиент делят один Postgres-checkpointer. Долгая память разделена по `from_user.id` (`X-User-Id`): профиль хранится отдельно у каждого участника, хотя тред группового чата общий.

```
# заполните .env по .env.example: LLM_*, LANGFUSE_*, TELEGRAM_BOT_TOKEN, POSTGRES_PASSWORD
docker compose up -d --build
```

Внутри compose `DATABASE_URL` смотрит на отдельный сервис `db`, а не на `postgres` Langfuse. Чекпоинты диалогов лежат в `parcel-pgdata`; профиль и `save_memory` — в `SqliteStore` на volume `parcel-store` (`/data/memory.db`). Проверка живучести:

```
docker compose restart api
curl -s localhost:8000/health
```

Разбор прогона и restart drill — в `runs/session-08.md`.

## Баланс провайдера

`balance.py` — починенная версия утилиты из лекции: читает `.env`, ходит в `/v2/balance` Polza и печатает доступную сумму, баланс и расход, не выводя ключ.

```
uv run python balance.py
```
