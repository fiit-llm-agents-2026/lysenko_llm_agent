# Session 8: deploy — FastAPI, Postgres-checkpointer, Telegram-бот

Практика ноутбука: вынести граф из ноутбука в сервис, подключить Postgres-чекпоинтер, поднять compose-стек, поговорить с ботом в Telegram, пережить `docker compose restart api` и выгрузить трейс одного хода.

## Что изменилось

| файл | роль |
|---|---|
| `service.py` | FastAPI вокруг `build_agent`: `POST /chat/{thread_id}` (SSE), `GET /health`, `AsyncPostgresSaver` в lifespan |
| `bot.py` | aiogram long polling; `thread_id = str(chat_id)`, запросы в API по HTTP |
| `Dockerfile`, `.dockerignore` | один образ для `api` и `bot`, `uv sync --frozen --no-dev` |
| `docker-compose.yml` | сервисы `api`, `bot`, `db`; volume `parcel-pgdata` и `parcel-store` |
| `run.py` | `log_tool_call` стал классом с `wrap_tool_call` и `awrap_tool_call` |
| `tests/test_service.py` | SSE-тест на фейковом графе, без сети и ключей |
| `.env.example` | `TELEGRAM_BOT_TOKEN`, `POSTGRES_PASSWORD`, `API_URL` |
| `balance.py` | починенная утилита проверки баланса Polza; ключ не печатается |
| `README.md` | разделы «Деплой» и «Баланс провайдера» |

`DATABASE_URL` задаётся только внутри `api` в compose, а не в `.env`: иначе переменную подхватил бы Postgres самого Langfuse. Чекпоинты — в отдельном сервисе `db`, не в `postgres`. Бот получает только `TELEGRAM_BOT_TOKEN` и `API_URL`, без LLM-ключа и пароля БД.

## Архитектура

```
Telegram
   │ long polling
   ▼
bot (aiogram) ── POST /chat/<chat_id> ──► api (FastAPI)
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                    AsyncPostgresSaver          SqliteStore
                    db:checkpoints             /data/memory.db
                              │
                              ▼
                         Langfuse trace
```

Бот не строит второй граф: он ходит в API, поэтому Telegram и веб-клиент делят один checkpointer и один путь трейсинга. Профиль и `save_memory` лежат в `SqliteStore` на volume: `patch_profile`/`desk_prompt` синхронные, а `AsyncPostgresStore` потребовал бы переписывать middleware.

## Запуск

```
docker compose up -d --build
curl -s localhost:8000/health
```

```
{"status":"ok","lane":"postgres"}
```

`setup()` создал таблицы при первом старте:

```
 Schema |         Name
--------+----------------------
 public | checkpoint_blobs
 public | checkpoint_migrations
 public | checkpoint_writes
 public | checkpoints
```

Бот в логах:

```
bot: @agents_course_la_bot | api: http://api:8000
```

## Поломки, найденные при прогоне

1. **Синхронный `wrap_tool_call` ломал async-путь.** Первый `POST /chat/api-drill-1` вернул `NotImplementedError: Asynchronous implementation of awrap_tool_call is not available`. `log_tool_call` был объявлен через `@wrap_tool_call` только для sync. Исправлено классом `LogToolCall(AgentMiddleware)` с обоими хуками; sync-путь `run.py`/`chat.py` продолжает работать.
2. **Бот съедал пробелы между токенами.** `.strip()` на каждом `data:`-чанке превращал `Hi Sasha!` в `HiSasha!`. Теперь снимается только обязательный один пробел после `data:`, остальные пробелы сохраняются.
3. **Терялись переводы строк и сырой Markdown.** Строки одного SSE-события склеивались через пустую строку, поэтому таблица прилипала к тексту (`AI-курсами.Найдено`), а Telegram показывал `|---|---|`. Парсер собирает строки события через `\n`, а `plain_text()` разворачивает Markdown-таблицы в строки ` · ` и убирает `**`/`__`/`` ` ``.
4. **Все Telegram-пользователи делили один профиль.** API брал `user_id` из `LANGFUSE_USER_ID`, поэтому `patch_profile`, `save_memory` и `desk_prompt` писали в один namespace. Бот теперь передаёт `X-User-Id: from_user.id`, а API кладёт его в `configurable.user_id`; тред по-прежнему общий на чат.

## Транскрипты

Чат `628030192`, бот `@agents_course_la_bot`.

**До рестарта**

```
user: Спасибо! Напомни в двух строках, какие курсы ты предложила и сколько где свободных мест
bot:  Два AI-курса: LLM Agents (пятница, 16:30, ауд. 412) — 25 свободных мест.
      Computer Vision (понедельник, 14:00, ауд. 301) — 20 свободных мест.
```

**Рестарт**

```
docker compose restart api
# api: Up (healthy), lane: postgres
```

**После рестарта**

```
user: После рестарта: какие курсы ты советовала и сколько там было свободных мест?
bot:  Я сохранила в память только то, что ты интересуешься AI-курсами; фактов о
      конкретных курсах и свободных местах там нет. Но по данным этого разговора:

      - LLM Agents (sc-02, пятница 16:30, ауд. 412) — 25 свободных мест
      - Computer Vision (sc-03, понедельник 14:00, ауд. 301) — 20 свободных мест

      Если хочешь, сохраню эти рекомендации в память и запишу тебя на один из курсов.
```

До рестарта в треде было 14 чекпоинтов; после рестарта ответ восстановлен из `db`, а не из памяти процесса. Дополнительно тот же drill пройден через API на треде `api-drill-2`: до рестарта — список AI-курсов, после — те же `sc-02` (25 мест) и `sc-03` (20 мест).

## Трейс

Экспорт: `runs/session-08-trace.json`.

```
id:            945f23e527ee567adc221fb67490f5e5
name:          session-08 telegram
sessionId:     628030192
userId:        sany1111
tags:          ["session-08", "telegram"]
observations:  21
generations:   3 (2 × model, 1 × patch_profile/extract_updates)
tools:         search_memories
tokens:        4 476 input + 379 output = 4 855
latency:       15 827 мс (trace list)
```

Трейс содержит именно ход после рестарта: `search_memories` вернул `Sasha is interested in AI courses.`, после чего модель ответила курсами из состояния треда. Профиль (`name=Sasha`, `interests=AI courses`) восстановлен из `SqliteStore` на volume.

Трейс снят до фикса изоляции пользователей, поэтому профиль в нём лежит в старом namespace `sany1111`. После фикса проверено на двух namespace: `audit-a` получил `name=Alice, interests=computer vision`, а `audit-b` остался пустым; `sessionId` по-прежнему равен чату.

## Проверка баланса

`balance.py` — исправленная версия утилиты из лекции; читает `.env`, ходит в `/v2/balance`, ключ не выводит.

```
uv run python balance.py
```

```
Можно потратить: 493,90 руб.
На балансе:      6 813,89 руб.
Потрачено всего: 187,80 руб.
Данные на:       2026-11-21T15:12:09.206Z
```

## Ограничения локального стека

- Langfuse 3.224.0 пишет `timestamp = 9999-12-31` и `latency = 0` в observations — тот же известный баг `langfuse#16858`, что и в session-07. Поэтому latency в артефакте взята из trace list (15 827 мс), а не из observation.
- В экспортированном трейсе `totalCost = 0`: локальный Langfuse не применил цену к `deepseek/deepseek-v4.1-flash@reasoning_effort=none`. Токены в observations корректны; при цене session-07 (`$0.15/1M` input, `$0.60/1M` output) ход стоит примерно `$0.000899`.
- `docker compose restart api` перезапускает только API; бот в это время получает `Сервис недоступен`, пока healthcheck не станет зелёным. Это ожидаемое поведение drill, повторный ход после рестарта проходит.

## Проверка кода

```
uv run pytest -q
# 5 passed
```

Тесты проверяют, что SSE отдаёт только сообщения узла `model`, пропускает `tools`, завершает поток `[DONE]`, что `/health` показывает ветку `memory` без `DATABASE_URL`, что `X-User-Id` доходит до `configurable.user_id`, что пустой текст получает `422`, что CRLF нормализуется в одно SSE-событие и что парсер бота склеивает строки одного события через `\n`.

Синхронный путь `run.py` после замены middleware отдельно проверен CLI-прогоном: `spec_course_find` → два `spec_course_info` → финальный ответ, без `NotImplementedError`.
