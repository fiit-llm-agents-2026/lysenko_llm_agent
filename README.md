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
