# Lysenko LLM agent

Ассистент по спецкурсам университета: ищет спецкурс, показывает расписание и свободные места, записывает студента. Каталог курсов фейковый и хранится в памяти.

## Запуск

```
cp .env.example .env
uv sync
uv run python run.py "What course can I take just to relax? Enroll me as Sasha."
uv run python run.py --mermaid
```

## Langfuse

`docker-compose.yml` — upstream Langfuse v3.224.0, `docker-compose.override.yml` создаёт проект из ключей в `.env`, подменяет образ minio (`cgr.dev` недоступен) и убирает проброс порта postgres на хост.

```
docker compose up -d
```

UI: http://localhost:3000. Если в `.env` заданы ключи Langfuse, каждый запуск `run.py` пишет трейс.
