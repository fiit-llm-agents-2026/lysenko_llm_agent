# Session 7: observability — сквозной трейс, prompt management, тест узла

Практика ноутбука: провести handler через все вызовы репозитория, собрать один multi-tool диалог в Langfuse, назвать самый медленный и самый дорогой узел по своим данным, унести системный промпт в prompt management и добавить бесплатный тест узла без инструментов.

## Что изменилось

`run.py`:

- `PROMPT_NAME = "special-courses-desk"`, `PROMPT_LABEL = "production"`;
- `prompt_source()` получает промпт по метке с кэшем и локальным fallback на `SYSTEM`;
- `--publish-prompt` публикует `SYSTEM` в Langfuse и печатает версию;
- `trace_metadata(thread, tags)` собирает `langfuse_session_id`, `langfuse_user_id`, `langfuse_tags` и `langfuse_prompt`;
- `new_trace_handler()` — единая фабрика `CallbackHandler`;
- `ask()` сам добавляет metadata, поэтому `run.py` и `load_test.py` не дублируют её;
- `EXTRACTOR` стал ленивым, а `summarize` — фабрикой `make_summarize(model)`: тест может подставить `FakeListChatModel` без ключа и без сети.

`chat.py`, `fork.py` и `load_test.py` переведены на общий `new_trace_handler()` и `trace_metadata()`; `fork.py` получил `--no-trace` и теперь трейсит и replay, и resume.

`tests/test_summarize.py` — тест узла `summarize`; `pytest` добавлен в dev-зависимости.

## Трассировка

Handler теперь проходит через все точки входа:

- `run.py` — CLI-прогон и `ask()`;
- `load_test.py` — каждый из 50 ходов;
- `chat.py` — каждый стрим, включая resume после гейта;
- `fork.py` — replay от чекпоинта и resume.

Metadata:

```python
{
    "langfuse_session_id": thread,          # один диалог — один id
    "langfuse_user_id": "sany1111",         # LANGFUSE_USER_ID
    "langfuse_tags": ["session-07", ...],
    "langfuse_prompt": <TextPromptClient>,  # версия промпта
}
```

Для `run.py`/`load_test.py` хендлер создаётся в `trace_callbacks()`/`new_trace_handler()`, для клиента и форка — на каждый стрим. Вложенные вызовы (`patch_profile` → trustcall, `summarize`) наследуют callbacks графа, поэтому их генерации попадают в тот же трейс.

## Prompt management

Системный промпт опубликован командой:

```
uv run python run.py --publish-prompt
```

```
[prompt] special-courses-desk v1 label production
```

Код больше не передаёт `SYSTEM` напрямую в `create_agent`: `system_prompt()` вызывает `get_prompt("special-courses-desk", label="production")` и компилирует текст. Локальная строка остаётся fallback'ом, если Langfuse недоступен. Динамические части (`Student card`, summary, `MEMORY_RULES`) остаются в коде — они зависят от состояния треда и стора.

В экспортированном трейсе все шесть генераций привязаны к `special-courses-desk` версии `1`:

```
prompt=special-courses-desk/1   (у каждой GENERATION)
```

## Диалог

Один реальный multi-tool прогон, `--store memory`, тред `obs-1`:

```
uv run python run.py --thread obs-1 --user u-sasha --store memory \
  "I'm Sasha and I like AI. Which AI courses have free seats? Enroll me as Sasha in the AI course with the most free seats."
```

Инструменты в трейсе:

```
spec_course_find(query="ai")
search_memories(query="student name and interests")
spec_course_info(course_id="sc-02")
spec_course_info(course_id="sc-03")
spec_course_enroll(course_id="sc-02", student="Sasha")
save_memory(fact="Student's name is Sasha and likes AI.")
save_memory(fact="Sasha enrolled in LLM Agents (sc-02), Friday 16:30, Room 412.")
```

Агент нашёл два AI-курса, сравнил свободные места (25 против 20) и записал Sasha на LLM Agents; затем сохранил имя, интерес и факт записи в память.

Трейс: `runs/session-07-trace.json`, id `4d7aaae7c13104f585c83bbbfc06ddc9`, 38 наблюдений, 6 генераций, 7 `TOOL`-спанов, `totalCost = $0.0007542`. Сессия `obs-1`, `user_id = sany1111`, теги `["multi-tool", "session-07"]`.

## Медленный и дорогой узлы

Самый медленный узел — `model`: 5 визитов, 13.59 с из 15.58 с трейса, самый долгий визит 4.56 с. Самый дорогой узел — тоже `model`: 5 400 токенов и $0.000608 из $0.000754; второй — `patch_profile.after_agent`: 1.89 с, 1 179 токенов, $0.000146.

| узел | визитов | всего, мс | максимум, мс | генераций | input | output | cache-read | цена |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `model` | 5 | 13 593.9 | 4 557.1 | 5 | 2 265 | 447 | 2 688 | $0.000608 |
| `patch_profile.after_agent` | 1 | 1 894.4 | 1 894.4 | 1 | 735 | 60 | 384 | $0.000146 |
| `tools` | 7 | 87.8 | 60.9 | 0 | — | — | — | — |
| `summarize.after_agent` | 1 | 1.2 | 1.2 | 0 | — | — | — | — |
| **итого** | | **15 577.3** | | **6** | **3 000** | **507** | **3 072** | **$0.000754** |

Токены сгруппированы по ближайшему узлу-родителю генерации: `model` — пять обычных вызовов, `patch_profile.after_agent` — trustcall-извлечение профиля. `tools` и `summarize` генераций не делают. `summarize` в этом прогоне ничего не сворачивает: в состоянии 13 сообщений, порог — 20.

Цена модели задана в Langfuse: `$0.15/1M` input и `$0.60/1M` output для `deepseek/deepseek-v4.1-flash`. Расчёт сходится с `totalCost` трейса:

```
model:          2265·1.5e-7 + 447·6e-7 = 0.00060795
patch_profile:   735·1.5e-7 +  60·6e-7 = 0.00014625
sum:                                    0.00075420
```

Cache-read в этой модели не тарифицирован отдельно, поэтому валютная оценка чуть занижена; в токенах cache-read учтён (3 072 штук). Если считать его по `$0.003/1M`, добавится ещё $0.0000092.

## Локальный баг latency

Langfuse в этом compose — 3.224.0, ClickHouse — 26.9; известный баг `langfuse#16858` пишет timestamp как `9999-12-31`, из-за чего per-node latency в UI равен 0. Trace-level latency (15 584 мс) при этом корректна. Поэтому таблица выше собрана локальным `BaseCallbackHandler` на том же прогоне: он записывает старт/конец каждого узла по `langgraph_node` и `langgraph_checkpoint_ns`, а вложенные trustcall-узлы отфильтрованы по `|` в namespace. Сумма по узлам (15 577 мс) совпадает с trace-level latency в пределах 7 мс, так что числа согласованы.

Сырой экспорт поэтому содержит `timestamp = 9999-12-31` и `latency = 0` у observations; токены, имена, prompt-версии и `totalCost` в нём корректны. Это ограничение локального стека, а не агента.

## Тест

`tests/test_summarize.py`:

```python
from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from run import make_summarize


def test_summarize_folds_old_messages():
    messages = []
    for index in range(10):
        messages += [HumanMessage(f"old question {index}"), AIMessage(f"old answer {index}")]
    messages.append(HumanMessage("the latest question"))

    node = make_summarize(FakeListChatModel(responses=["a short summary"]))
    update = node.after_agent({"messages": messages}, None)

    assert update["summary"] == "a short summary"
    assert len(update["messages"]) == 20
    assert all(isinstance(message, RemoveMessage) for message in update["messages"])
```

```
$ uv run pytest -q
.                                                                        [100%]
1 passed, 1 warning in 0.18s
```

Тест не читает ключ и не делает запрос: `FakeListChatModel` отдаёт заготовленный ответ, а `make_summarize` принимает модель аргументом. Проверены форма partial update, текст summary и количество `RemoveMessage`; качество summary — задача session 11.

## Сегодня в одной карточке

- Трейсинг обязателен на всех входах: `run.py`, `load_test.py`, `chat.py`, `fork.py`; metadata несёт сессию, GitHub handle, тег и версию промпта.
- Промпт `special-courses-desk` с меткой `production` живёт в Langfuse; код получает его по метке, а `--publish-prompt` создаёт новую версию.
- По своим данным самый медленный и самый дорогой узел — `model`; `patch_profile.after_agent` — второй по агрегату (1 179 токенов, $0.000146), но самая дорогая отдельная генерация тоже у `model` ($0.000175 за вызов 862/76).
- `FakeListChatModel`-тест ловит форму узла бесплатно; это первый шаг к регрессиям, которые больше не нужно искать глазами в UI.
- Локальный стек Langfuse пишет span-времена как `9999-12-31`; trace-level latency и токены пригодны, per-node latency приходится мерить локально до обновления ClickHouse/Langfuse.
