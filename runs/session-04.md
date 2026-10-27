# Session 4: краткосрочная память — checkpointer, суммаризация, SqliteSaver

## Что изменилось

`run.py`:

- `build_agent(checkpointer=None, summarization=True)` передаёт checkpointer в `create_agent`; CLI собирает агента над `SqliteSaver(assistant.db)`, нагрузочный тест — над `InMemorySaver`.
- `ask(agent, text, thread_id, callbacks)` отправляет только новое сообщение и кладёт `thread_id` в `configurable`; историю держит тред. Флаг `--thread NAME` (по умолчанию `desk`).
- `CoursesState(AgentState)` с полем `summary: NotRequired[str]` — без редьюсера, каждая запись заменяет.
- `@dynamic_prompt prompt_with_summary` — summary едет вместе с `SYSTEM` в каждом вызове модели.
- `@after_agent summarize` — раз за ход, после финального ответа: если в треде больше 20 сообщений, модель сворачивает историю (вместе с прошлым summary) в новое summary, старые сообщения удаляются через `RemoveMessage`. Последний ход остаётся целиком: срез идёт по последнему `HumanMessage`, а не `[:-2]`, потому что tool-result без своего tool-call провайдер отвергает.

`*.db*` добавлен в `.gitignore`.

Граф (`uv run python run.py --mermaid`): `model ⇄ tools`, из `model` — ребро в `summarize.after_agent`, оттуда в `__end__`.

## Почему суммаризация, а не окно

Диалог со столом спецкурсов постоянно ссылается назад: «на что я записан», «на что записан Тим», «как меня зовут». Скользящее окно молча выбрасывает именно ранние факты — имя и курс из первого хода уйдут первыми. Суммаризация сублинейна по токенам, но платит лишним вызовом модели и теряет всё, о чём не попросил промпт свёртки. Цена этого выбора — ниже, в цифрах.

## Токены до и после

`uv run python load_test.py` прогоняет один и тот же 50-ходовой диалог дважды против живой модели (`deepseek/deepseek-v4.1-flash` через Polza): сначала с выключенным `summarize` (full buffer), затем с включённым. Числа — `usage_metadata` из ответов модели, собранные callback-хендлером; полный вывод — `runs/session-04-load-test.txt`.

| ход | buffer: промпт | buffer: сообщений | summary: промпт | summary: сообщений |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 760 | 7 | 760 | 7 |
| 7 | 1284 | 25 | 1224 | 4 |
| 10 | 1980 | 42 | 1451 | 7 |
| 20 | 2874 | 69 | 1122 | 14 |
| 30 | 3586 | 93 | 1067 | 4 |
| 40 | 4452 | 121 | 1454 | 18 |
| 50 | 5118 | 143 | 1252 | 8 |

«Промпт» — самый большой вход за ход; «сообщений» — сколько осталось в чекпоинте после хода.

| | входные токены, 50 ходов | выходные токены, 50 ходов | самый большой промпт |
| --- | ---: | ---: | ---: |
| full buffer | 205 079 | 3 356 | 5 118 |
| суммаризация | 103 098 | 6 791 | 1 893 |

Суммаризация вдвое срезает вход (−50%) и держит промпт плоским: у буфера он растёт каждый ход и к 50-му доходит до 5118 токенов, у суммаризации не выходит за 1893 и на последнем ходу стоит на 1252. Чекпоинт буфера к концу держит 143 сообщения, суммаризации — 8.

Обратная сторона: выходных токенов вдвое больше (3356 → 6791). `summarize` сработал 8 раз (ходы 7, 10, 15, 23, 29, 35, 42, 47 — там, где число сообщений падает до 2–7), и каждое summary — это 150–500 токенов генерации. Суммаризация не бесплатна: она переносит трату с входа на выход и выигрывает только потому, что растёт без предела именно вход.

По тарифу DeepSeek V4.1 Flash без учёта кэша ($0.15/1M вход, $0.60/1M выход): буфер ≈ $0.033, суммаризация ≈ $0.020 за 50 ходов. Оговорка: буфер дописывает историю только в хвост, и провайдер выставляет повторный префикс по кэш-тарифу; каждая свёртка переписывает начало промпта и сбрасывает кэш. Реальный разрыв в деньгах меньше, чем в токенах.

## Что потеряла суммаризация

Ход 1: «I'm Sasha, second-year master's student in applied math, I study at the CS faculty. What courses are about AI?». Ход 50 спрашивает все четыре личных факта обратно — **оба режима ответили верно**: промпт свёртки явно просит «the student's name and personal facts», и факты пережили все 8 свёрток.

Потерялось другое — то, о чём промпт не просил. Ход 47: «What was the first course I asked you about today?»

- full buffer: «You first asked about **AI courses**, which turned up **LLM Agents** (sc-02) and **Computer Vision** (sc-03).» — верно.
- суммаризация: «**sc-01 — Chill Course** (Tuesday 18:00, Room 105, A. Petrov) was the first course you asked about.» — неверно, и уверенно.

Порядок разговора в summary не входит: после нескольких свёрток там остался список курсов и записей, но не то, с чего всё началось. Модель не сказала «не знаю», а выбрала курс по первому id. Это и есть тихий отказ суммаризации: summary хранит ровно то, что попросил промпт, остальное исчезает навсегда, потому что исходные сообщения удалены через `RemoveMessage`.

## Перезапуск

Два отдельных процесса `python`, один тред `drill`. Между ними — только `assistant.db`.

Первый процесс:

```
$ uv run python run.py --thread drill "Hi, I am Sasha, second-year master's in applied math. Enroll me in the LLM Agents course."
langfuse: http://localhost:3000 | up: True
[tool] spec_course_find({'query': 'agents'})
[tool] spec_course_enroll({'course_id': 'sc-02', 'student': 'Sasha'})
================================ Human Message =================================

Hi, I am Sasha, second-year master's in applied math. Enroll me in the LLM Agents course.
================================== Ai Message ==================================

I'll look up the LLM Agents course for you.
Tool Calls:
  spec_course_find (call_2b000b62dd1f47ab94c3bdee15d912d6)
 Call ID: call_2b000b62dd1f47ab94c3bdee15d912d6
  Args:
    query: agents
================================= Tool Message =================================
Name: spec_course_find

sc-02: LLM Agents
================================== Ai Message ==================================
Tool Calls:
  spec_course_enroll (call_412041622b124629862b4bd4cd7f384b)
 Call ID: call_412041622b124629862b4bd4cd7f384b
  Args:
    course_id: sc-02
    student: Sasha
================================= Tool Message =================================
Name: spec_course_enroll

Enrolled Sasha in LLM Agents. 24 seats left.
================================== Ai Message ==================================

Done — you're enrolled in LLM Agents (sc-02). 24 seats remain. Want the schedule, room, and instructor details?
[state] thread=drill | 6 messages | summary: none yet
```

Второй процесс, запущенный после выхода первого:

```
$ uv run python run.py --thread drill "Which course did I enroll in, what is my name, and what year am I in?"
langfuse: http://localhost:3000 | up: True
================================ Human Message =================================

Which course did I enroll in, what is my name, and what year am I in?
================================== Ai Message ==================================

You enrolled in **LLM Agents** (course id sc-02). Your name is **Sasha**, and you're a **second-year master's** student in applied math.
[state] thread=drill | 8 messages | summary: none yet
```

Тред продолжился с 6 сообщений до 8. Оговорка: пережила перезапуск история, а не сами записи — `ENROLLMENTS` живёт в RAM, и после рестарта `spec_course_info` снова покажет 25 свободных мест. Состояние домена между процессами — задача long-term памяти (session 5).

## Трейс

`runs/session-04-trace.json` — ход 7 нагрузочного теста в режиме суммаризации («Fine, enroll me there as well.», тред `load-summary`), первый ход, на котором сработал `summarize`. Дерево:

- `model` → `ChatOpenAI` (1224 вход / 63 выход) → `tools` → `spec_course_enroll` → `model` → `ChatOpenAI` (1140 / 61) — сам ход;
- `summarize.after_agent` → `ChatOpenAI` (812 / 150) — написание summary, отдельная генерация, оплачиваемая отдельно от ответа.

Выход спана `summarize.after_agent` — новое `summary` и список `RemoveMessage` на 19 сообщений (из 23 остаётся последний ход, 4 сообщения). Первая строка summary под заголовком — «Sasha is a second-year master's student in applied math, studying at the CS faculty» — та самая строка, на которой держится правильный ответ на 50-м ходу.
