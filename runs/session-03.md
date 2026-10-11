# Session 3: агент на `create_agent`, middleware и схемы инструментов

## Что изменилось

Граф из session-02 остаётся в истории git (коммит `d11c89b`). В `run.py` `build_graph()` с `StateGraph`/`ToolNode`/`tools_condition` заменён на `build_agent()` — один вызов:

```python
create_agent(chat_model("cheap"), TOOLS, system_prompt=SYSTEM, middleware=[log_tool_call])
```

`create_agent` компилирует тот же граф `model ⇄ tools`, что собирался руками в session-02.

Инструменты домена — три, с общим префиксом `spec_course_`: `spec_course_find` отдаёт id, `spec_course_info` и `spec_course_enroll` принимают этот id. Промахи остаются подсказкой, а не исключением. Всем добавлен `parse_docstring=True`, поэтому строки `Args:` попадают в описания параметров на провод.

## Схемы инструментов

`uv run python run.py --schemas` печатает словарь, который уезжает в тело каждого запроса:

### spec_course_find

```json
{
  "type": "function",
  "function": {
    "name": "spec_course_find",
    "description": "Find university special courses by one word.",
    "parameters": {
      "properties": {
        "query": {
          "description": "A title word, a topic tag or a weekday, for example 'ai' or 'friday'. Returns course ids for spec_course_info and spec_course_enroll.",
          "type": "string"
        }
      },
      "required": [
        "query"
      ],
      "type": "object"
    }
  }
}
```

### spec_course_info

```json
{
  "type": "function",
  "function": {
    "name": "spec_course_info",
    "description": "Show the schedule, room, teacher and free seats of one course.",
    "parameters": {
      "properties": {
        "course_id": {
          "description": "A course id from spec_course_find, for example 'sc-01'.",
          "type": "string"
        }
      },
      "required": [
        "course_id"
      ],
      "type": "object"
    }
  }
}
```

### spec_course_enroll

```json
{
  "type": "function",
  "function": {
    "name": "spec_course_enroll",
    "description": "Enroll the named student in one course.",
    "parameters": {
      "properties": {
        "course_id": {
          "description": "A course id from spec_course_find, for example 'sc-02'.",
          "type": "string"
        },
        "student": {
          "description": "Name of the student to enroll.",
          "type": "string"
        }
      },
      "required": [
        "course_id",
        "student"
      ],
      "type": "object"
    }
  }
}
```

Модель читает `description` функции и `description` каждого параметра — это и есть промпт; тело функции и код `Args:` больше нигде не участвуют.

## Middleware: лог каждого вызова инструмента

`@wrap_tool_call` видит вызов до выполнения и передаёт его дальше в `handler`:

```python
@wrap_tool_call
def log_tool_call(request, handler):
    print(f"[tool] {request.tool_call['name']}({request.tool_call['args']})")
    return handler(request)
```

## Трассированный диалог

`uv run python run.py "Are there free seats on the LLM agents course? Enroll me as Sasha if so."`

```
langfuse: http://localhost:3000 | up: True
[tool] spec_course_find({'query': 'llm'})
[tool] spec_course_info({'course_id': 'sc-02'})
[tool] spec_course_enroll({'course_id': 'sc-02', 'student': 'Sasha'})
================================ Human Message =================================

Are there free seats on the LLM agents course? Enroll me as Sasha if so.
================================== Ai Message ==================================

I'll look up the course first.
Tool Calls:
  spec_course_find (call_19b8d0563d144e31ad23353d7f964522)
 Call ID: call_19b8d0563d144e31ad23353d7f964522
  Args:
    query: llm
================================= Tool Message =================================
Name: spec_course_find

sc-02: LLM Agents
================================== Ai Message ==================================
Tool Calls:
  spec_course_info (call_56f315e1ede7455a9dbca07d5c28a968)
 Call ID: call_56f315e1ede7455a9dbca07d5c28a968
  Args:
    course_id: sc-02
================================= Tool Message =================================
Name: spec_course_info

LLM Agents: Friday 16:30, Room 412, teacher I. Smirnov, 25 seats free.
================================== Ai Message ==================================

Seats are free, so I'll enroll you.
Tool Calls:
  spec_course_enroll (call_b5994ec261184aaca0b8793d719ae8b6)
 Call ID: call_b5994ec261184aaca0b8793d719ae8b6
  Args:
    course_id: sc-02
    student: Sasha
================================= Tool Message =================================
Name: spec_course_enroll

Enrolled Sasha in LLM Agents. 24 seats left.
================================== Ai Message ==================================

Yes — LLM Agents (sc-02) had 25 free seats. You're enrolled as Sasha; 24 seats remain. It meets Fridays at 16:30 in Room 412 with I. Smirnov.
```

Ответ потребовал трёх вызовов: `spec_course_find` вернул `sc-02` в третьем сообщении, и этот id стал аргументом `spec_course_info` и `spec_course_enroll`. Три строки `[tool]` сверху — вывод middleware, по одной на вызов.

## Счётчики и цена

В трейсе четыре запроса к модели:

| запрос | вход (cache-miss) | вход (cache-hit) | выход | всего |
| --- | ---: | ---: | ---: | ---: |
| 1 | 533 | 0 | 49 | 582 |
| 2 | 600 | 0 | 43 | 643 |
| 3 | 295 | 384 | 71 | 750 |
| 4 | 774 | 0 | 48 | 822 |
| **итого** | **2202** | **384** | **211** | **2797** |

Самый дорогой запрос — четвёртый (822 токена: 774 входных + 48 выходных). Причина в счётчике: к этому моменту в истории уже лежат system, реплика пользователя и три пары tool-call/tool-result, и вся история пересылается заново — вход растёт с каждым ходом (533 → 600 → 679 → 774).

Цена по тарифу DeepSeek V4.1 Flash (off-peak: $0.15/1M cache-miss input, $0.003/1M cache-hit input, $0.60/1M output — канал Polza перепродаёт DeepSeek): `2202/1M·$0.15 + 384/1M·$0.003 + 211/1M·$0.60 ≈ $0.00046` за прогон.

Одним предложением: весь диалог с тремя вызовами инструментов стоит ≈ 0.046 цента ($0.00046) — 2797 токенов, из которых почти весь объём это дешёвый вход.

## Трейс

`runs/session-03-trace.json` — экспорт из локального Langfuse. Один трейс `LangGraph`: четыре генерации `ChatOpenAI` со счётчиками выше, между ними три спана-инструмента (`spec_course_find`, `spec_course_info`, `spec_course_enroll`). Кэш-хит на третьем запросе (384 токена) — префикс истории уже был отправлен на предыдущих ходах, и провайдер выставил его по другому тарифу.
