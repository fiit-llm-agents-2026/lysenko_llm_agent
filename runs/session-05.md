# Session 5: долгосрочная память — store по человеку, два писателя

Session 4 дал ассистенту checkpointer: один `thread_id`, один разговор, переживает рестарт. Новый `thread_id` — всё ещё незнакомец. Session 5 добавляет вторую память: `store`, ключ — человек, а не разговор. `create_agent` принимает и `checkpointer=`, и `store=`; граф раздаёт сторе и нодам, и тулам.

Два писателя, в порядке ноутбука:

- фоновой: `patch_profile`, хук `after_agent`, — отдает законченный ход trustcall-экстрактору, тот патчит документ `Profile` в сторе через `existing=`;
- горячий путь: `save_memory` / `search_memories` — обычные тулы session-3 поверх того же стора, модель зовёт их внутри хода.

Всё именуется по человеку: `("profiles", user_id())` и `("memories", user_id())`, `user_id` читается из `configurable.user_id` (CLI `--user`), никогда из треда.

## Что изменилось

`run.py`:

- `build_store(kind, path)` — `SqliteStore(memory.db)` (по умолчанию) или `InMemoryStore`; для sqlite нужно `isolation_level=None` на соединении и `store.setup()` при первом использовании.
- `user_id()` — из `get_config()["configurable"]`; дефолт `guest`.
- `save_memory` / `search_memories` — тулы через `get_store()`, namespace `("memories", user_id())`.
- `Profile` — pydantic-схема под домен: `name` / `program` / `interests` / `constraints`; `EXTRACTOR = create_extractor(cheap_model(), tools=[Profile], tool_choice="Profile")`.
- `patch_profile` — `after_agent`: читает текущий документ, передает его как `existing={"Profile": ...}`, пишет пропатченный обратно.
- `desk_prompt` (бывший `prompt_with_summary`) — к `SYSTEM` добавляет `MEMORY_RULES` и строку `Student card: {...}`, когда стор есть; summary — как раньше.
- `build_agent(checkpointer, summarization, store)` — тулы памяти, `MEMORY_RULES` и `patch_profile` появляются только при `store is not None`: lane без стора (нагрузочный тест session 4) не меняется.
- CLI: `--user NAME` (дефолт `guest`), `--store sqlite|memory` (дефолт `sqlite`); после хода печатает `[profile]` и `[memories]` — стор, прочитанный обратно.

`pyproject.toml`: `trustcall==0.0.39`.

Граф (`uv run python run.py --mermaid`): `model ⇄ tools`, после ответа `model → patch_profile.after_agent → summarize.after_agent → __end__`. Фоновой писатель успевает до суммаризации, так что суммаризация сворачивает ход, уже записанный в профиль.

## Диалог один: три хода, которые учат стол

Тред `visit-1`, юзер `u-sasha`, каждый ход — отдельный процесс. Строки `[profile]` / `[memories]` в конце — стор, прочитанный после хода.

Ход 1. Стол слышит имя, программу и интересы; заодно отвечает по делу.

`uv run python run.py --thread visit-1 --user u-sasha "Hi! I'm Sasha, a second-year master's student in applied math. I'm into LLMs and AI in general. Which courses touch on agents or AI?"`

```
langfuse: http://localhost:3000 | up: True
[tool] spec_course_find({'query': 'ai'})
[tool] spec_course_find({'query': 'agents'})
[tool] search_memories({'query': 'Sasha background and enrollments'})
[tool] spec_course_info({'course_id': 'sc-03'})
[tool] spec_course_info({'course_id': 'sc-02'})
[tool] save_memory({'fact': 'Sasha is interested in LLMs and AI generally.'})
[tool] save_memory({'fact': "Sasha is a second-year master's student in applied math."})
================================ Human Message =================================

Hi! I'm Sasha, a second-year master's student in applied math. I'm into LLMs and AI in general. Which courses touch on agents or AI?
================================== Ai Message ==================================

I'll look that up for you, Sasha.
Tool Calls:
  spec_course_find (call_09143f915bff468d9409b314b4296939)
 Call ID: call_09143f915bff468d9409b314b4296939
  Args:
    query: ai
  spec_course_find (call_1dfaee7d72d046cda045783a11a1b5e7)
 Call ID: call_1dfaee7d72d046cda045783a11a1b5e7
  Args:
    query: agents
  search_memories (call_23f7aa3ba8b24575b38999b9e52920a9)
 Call ID: call_23f7aa3ba8b24575b38999b9e52920a9
  Args:
    query: Sasha background and enrollments
================================= Tool Message =================================
Name: spec_course_find

sc-02: LLM Agents; sc-03: Computer Vision
================================= Tool Message =================================
Name: spec_course_find

sc-02: LLM Agents
================================= Tool Message =================================
Name: search_memories

nothing stored about this student yet
================================== Ai Message ==================================

Welcome, Sasha! Good to meet you. Let me pull the details on those two.
Tool Calls:
  spec_course_info (call-db748de3-2904-4b68-a734-07516627a140)
 Call ID: call-db748de3-2904-4b68-a734-07516627a140
  Args:
    course_id: sc-02
  spec_course_info (call-7872c9d8-3536-4cfb-8724-9e2ccf8ee7a0)
 Call ID: call-7872c9d8-3536-4cfb-8724-9e2ccf8ee7a0
  Args:
    course_id: sc-03
================================= Tool Message =================================
Name: spec_course_info

LLM Agents: Friday 16:30, Room 412, teacher I. Smirnov, 25 seats free.
================================= Tool Message =================================
Name: spec_course_info

Computer Vision: Monday 14:00, Room 301, teacher E. Volkova, 20 seats free.
================================== Ai Message ==================================

Hi Sasha — nice to meet you! Two courses here touch on your interests:

**sc-02 — LLM Agents** (the closest fit for agents/AI)
- Friday 16:30, Room 412, teacher I. Smirnov, 25 seats free

**sc-03 — Computer Vision** (AI, but a different subfield)
- Monday 14:00, Room 301, teacher E. Volkova, 20 seats free

Want me to enroll you in either one?
Tool Calls:
  save_memory (call_fa7815d6801b432c9b113e085cd4447f)
 Call ID: call_fa7815d6801b432c9b113e085cd4447f
  Args:
    fact: Sasha is a second-year master's student in applied math.
  save_memory (call_a02b4fb5672744399941f6829b4c235b)
 Call ID: call_a02b4fb5672744399941f6829b4c235b
  Args:
    fact: Sasha is interested in LLMs and AI generally.
================================= Tool Message =================================
Name: save_memory

saved as cd28a71c
================================= Tool Message =================================
Name: save_memory

saved as 7948c11a
================================== Ai Message ==================================

I've noted your background and interests for next time. Just say the word and I'll enroll you in LLM Agents (or Computer Vision).
[state] thread=visit-1 | 12 messages | summary: none yet
[profile] u-sasha: {"name": "Sasha", "program": "second-year master's in applied math", "interests": "LLMs and AI", "constraints": null}
[memories] u-sasha: Sasha is interested in LLMs and AI generally.; Sasha is a second-year master's student in applied math.
```

Первая же попытка `search_memories` на незнакомом человеке — «nothing stored»: модель честно проверяет, прежде чем отвечать.

Ход 2. Запись — тул session 2; ограничение — новый факт. В этот раз `spec_course_find` не понадобился: айди sc-02 уже в истории треда.

`uv run python run.py --thread visit-1 --user u-sasha "Enroll me in LLM Agents, please. One thing to remember: I can't attend on Mondays, so no Monday courses for me."`

```
langfuse: http://localhost:3000 | up: True
[tool] spec_course_enroll({'course_id': 'sc-02', 'student': 'Sasha'})
[tool] save_memory({'fact': 'Sasha cannot attend courses on Mondays.'})
================================ Human Message =================================

Enroll me in LLM Agents, please. One thing to remember: I can't attend on Mondays, so no Monday courses for me.
================================== Ai Message ==================================
Tool Calls:
  spec_course_enroll (call-96c44449-0a6b-408f-a3aa-77635f388db3)
 Call ID: call-96c44449-0a6b-408f-a3aa-77635f388db3
  Args:
    course_id: sc-02
    student: Sasha
  save_memory (call-7d6bafab-cfc9-420e-bcbf-828c30ea1039)
 Call ID: call-7d6bafab-cfc9-420e-bcbf-828c30ea1039
  Args:
    fact: Sasha cannot attend courses on Mondays.
================================= Tool Message =================================
Name: spec_course_enroll

Enrolled Sasha in LLM Agents. 24 seats left.
================================= Tool Message =================================
Name: save_memory

saved as 37a79b17
================================== Ai Message ==================================

Done — you're enrolled in **LLM Agents** (Friday 16:30, Room 412, I. Smirnov). 24 seats left.

And I've noted that Mondays don't work for you — so I'll steer you away from Monday courses like Computer Vision in the future.
[state] thread=visit-1 | 17 messages | summary: none yet
[profile] u-sasha: {"name": "Sasha", "program": "second-year master's in applied math", "interests": "LLMs and AI", "constraints": "no Monday courses"}
[memories] u-sasha: Sasha cannot attend courses on Mondays.; Sasha is interested in LLMs and AI generally.; Sasha is a second-year master's student in applied math.
```

Ход 3. Поправка: ход называет ровно одно — перевод на другую программу.

`uv run python run.py --thread visit-1 --user u-sasha "One correction for your records: I've transferred to the CS faculty, so I'm a first-year master's in computer science now, not applied math."`

```
langfuse: http://localhost:3000 | up: True
[tool] save_memory({'fact': 'Sasha transferred to the CS faculty.'})
[tool] save_memory({'fact': "Sasha is now a first-year master's student in computer science (previously applied math)."})
================================ Human Message =================================

One correction for your records: I've transferred to the CS faculty, so I'm a first-year master's in computer science now, not applied math.
================================== Ai Message ==================================
Tool Calls:
  save_memory (call_8c3797d7b5af4eceb23a4913d790efcc)
 Call ID: call_8c3797d7b5af4eceb23a4913d790efcc
  Args:
    fact: Sasha transferred to the CS faculty.
  save_memory (call_751d67c7f48b468a95448ffe9480eb8f)
 Call ID: call_751d67c7f48b468a95448ffe9480eb8f
  Args:
    fact: Sasha is now a first-year master's student in computer science (previously applied math).
================================= Tool Message =================================
Name: save_memory

saved as 63229249
================================= Tool Message =================================
Name: save_memory

saved as 19fb8118
================================== Ai Message ==================================

Got it — thanks for the correction. I've updated your record: you're now a **first-year master's in computer science**, having transferred to the CS faculty from applied math. Your interest tags (LLMs/AI) and your no-Monday constraint still stand.
[state] thread=visit-1 | 5 messages | summary: **Summary**

- **Student:** Sasha — transferred to the CS faculty; now a first-y...
[profile] u-sasha: {"name": "Sasha", "program": "first-year master's in computer science", "interests": "LLMs and AI", "constraints": "no Monday courses"}
[memories] u-sasha: Sasha transferred to the CS faculty.; Sasha is now a first-year master's student in computer science (previously applied math).; Sasha cannot attend courses on Mondays.; Sasha is interested in LLMs and AI generally.; Sasha is a second-year master's student in applied math.
```

Ход 3 перевалил тред за 20 сообщений — сработал `summarize` из session 4 (строка `[state]` с summary, история свёрнута до последнего хода). Две памяти сосуществуют в одном графе: summary держит разговор, стор держит человека.

## Патч против регенерации

Ход 3 не называет ни имени, ни интересов, ни ограничений — и все три выживают:

```
до:    {"name": "Sasha", "program": "second-year master's in applied math", "interests": "LLMs and AI", "constraints": "no Monday courses"}
после: {"name": "Sasha", "program": "first-year master's in computer science", "interests": "LLMs and AI", "constraints": "no Monday courses"}
```

Это `existing=`. `patch_profile` читает документ из стора и отдает его экстрактору как `{"Profile": item.value}`; trustcall просит у модели JSON Patch против этого документа, а не свежий документ. Регенерация целого профиля из хода, где упомянуто одно поле, — так поля и теряются.

`save_memory` не патчит, а дописывает: после хода 3 в списке фактов лежат и «Sasha is a second-year master's student in applied math.», и «Sasha is now a first-year master's student in computer science...» — рядом, оба выглядят одинаково правдоподобно. У пропатченного документа одна программа; у append-only списка — все программы, которые у неё когда-либо были. Это цена второго писателя, и она выстрелит в диалоге два.

Правило «один факт на вызов» адресовано модели, не trustcall: список фактов пишет `save_memory`, обычный `@tool`, поэтому фраза сидит в системном промпте — и транскрипты показывают, что держится (два отдельных вызова в ходе 1, ещё два в ходе 3).

## Чьё имя попадёт в профиль

`spec_course_enroll(course_id, student)` принимает имя со времён session 3, и студенты записывают друзей. `patch_profile` отдает экстрактору весь ход, тулколлы включительно — имя друга стоит рядом с именем говорящего, и профиль в одном плохом извлечении от подмены.

Сначала сюрприз: со карточкой в промпте стол сам отказывается записывать друга.

`uv run python run.py --thread book-friend --user u-sasha "Enroll my friend Tim in the Board Game Theory course, please."`

```
I can help with course enrollments, but I can only enroll the student I have on file —
and I'm not able to enroll a third party like your friend Tim. If Tim is the student,
I'd need his own details.
[state] thread=book-friend | 2 messages | summary: none yet
[profile] u-sasha: {"name": "Sasha", "program": "first-year master's in computer science", "interests": "LLMs and AI", "constraints": "no Monday courses"}
```

Переформулировка («Enroll him in Board Game Theory under his own name, not mine») даёт то же: «I can only act for the student whose card is on file (you, Sasha)». Это овер-рестрикция, побочный эффект строки `Student card` в промпте: стол заякорился на одного человека. A/B без карточки (свежий сторе — строки карточки в промпте нет):

`uv run python run.py --store memory --thread friend-nocard --user u-plain "Hi, I'm Sasha. My groupmate Tim wants to join Board Game Theory. Enroll him under his own name, not mine."`

```
[tool] spec_course_find({'query': 'board game theory'})
[tool] search_memories({'query': 'Sasha'})
[tool] spec_course_find({'query': 'games'})
[tool] spec_course_info({'course_id': 'sc-04'})
[tool] spec_course_enroll({'course_id': 'sc-04', 'student': 'Tim'})
[tool] save_memory({'fact': "Sasha's groupmate is Tim, who is enrolled in Board Game Theory (sc-04)."})
```

Без карточки запись Тима проходит штатно. Значит, экстрактор всё равно обязан уметь пережить ход с чужим именем. Реплей такого хода через экстрактор (сообщение + тулколл записи Тима + результат), пять прогонов на вариант:

```
bare field       ['Sasha', 'Tim', 'Sasha', 'Sasha', 'Tim']
field + rule     ['Sasha', None, 'Sasha', 'Sasha', 'Sasha']
```

«Bare field» — очевидный первый драфт: `name` с описанием «First name of the student.». Он теряет гостя в 2 из 5 прогонов и записывает Тима. «Field + rule» — то, что в коде: описание поля «never a name enrolled for someone else» плюс `PROFILE_RULE` системным сообщением перед ходом. Десять прогонов с гардом: Тим не записан ни разу; один прогон из десяти вернул `None` вместо имени — патч защищает от подмены, но не от модели, «зачистившей» поле, которое ход не упоминал. Вторая партия из пяти прогонов вернула карточку без изменений все пять раз, `json_doc_id: Profile` — режим патча, а не регенерации.

## Диалог два: свежий thread_id узнаёт Сашу

Новый процесс, тред `visit-2`: в чекпоинтере пусто, истории нет вообще. Этот ход — recognition-ран, его трейс ниже.

`uv run python run.py --thread visit-2 --user u-sasha "Morning! Anything on the board I would like?"`

```
langfuse: http://localhost:3000 | up: True
[tool] spec_course_find({'query': 'ai'})
[tool] search_memories({'query': 'enrollments and interests'})
[tool] spec_course_info({'course_id': 'sc-03'})
[tool] spec_course_info({'course_id': 'sc-02'})
================================ Human Message =================================

Morning! Anything on the board I would like?
================================== Ai Message ==================================

Good morning, Sasha! Let me check what's available and what I know about you.
Tool Calls:
  search_memories (call-f323a8d7-e724-4418-978a-a02540d517c4)
 Call ID: call-f323a8d7-e724-4418-978a-a02540d517c4
  Args:
    query: enrollments and interests
  spec_course_find (call-22b2fdf4-0d59-4852-8df4-18f62c4532d3)
 Call ID: call-22b2fdf4-0d59-4852-8df4-18f62c4532d3
  Args:
    query: ai
================================= Tool Message =================================
Name: search_memories

Sasha transferred to the CS faculty.; Sasha is now a first-year master's student in computer science (previously applied math).; Sasha cannot attend courses on Mondays.; Sasha is interested in LLMs and AI generally.; Sasha is a second-year master's student in applied math.
================================= Tool Message =================================
Name: spec_course_find

sc-02: LLM Agents; sc-03: Computer Vision
================================== Ai Message ==================================
Tool Calls:
  spec_course_info (call-e6e12111-40ad-413c-8852-fe0133e7284d)
 Call ID: call-e6e12111-40ad-413c-8852-fe0133e7284d
  Args:
    course_id: sc-02
  spec_course_info (call-fdeede42-480d-4301-9ed9-fdbd9c510188)
 Call ID: call-fdeede42-480d-4301-9ed9-fdbd9c510188
  Args:
    course_id: sc-03
================================= Tool Message =================================
Name: spec_course_info

LLM Agents: Friday 16:30, Room 412, teacher I. Smirnov, 25 seats free.
================================= Tool Message =================================
Name: spec_course_info

Computer Vision: Monday 14:00, Room 301, teacher E. Volkova, 20 seats free.
================================== Ai Message ==================================

Morning, Sasha! Here's what's on the board for AI folks:

- **LLM Agents** (sc-02) — Friday 16:30, Room 412, I. Smirnov, 25 seats free. Right up your alley, and no Monday conflict.
- **Computer Vision** (sc-03) — Monday 14:00, Room 301, E. Volkova, 20 seats free. Good course, but it clashes with your no-Monday rule.

So **LLM Agents** looks like the clear pick. Want me to enroll you?
[state] thread=visit-2 | 8 messages | summary: none yet
[profile] u-sasha: {"name": "Sasha", "program": "first-year master's in computer science", "interests": "LLMs and AI", "constraints": "no Monday courses"}
[memories] u-sasha: Sasha transferred to the CS faculty.; Sasha is now a first-year master's student in computer science (previously applied math).; Sasha cannot attend courses on Mondays.; Sasha is interested in LLMs and AI generally.; Sasha is a second-year master's student in applied math.
```

Откуда что взялось, по писателям:

- приветствие по имени и поиск по интересам (`ai`) — строка `Student card`, которую `desk_prompt` кладёт в системный промпт; прочитана из `("profiles", "u-sasha")`, фоновой писатель;
- `search_memories` — горячий путь, читает `("memories", "u-sasha")`;
- «it clashes with your no-Monday rule» — карточка снова: `constraints` применена к раскладу курсов без единого слова от пользователя.

Системный промпт первого модельного вызова этого хода, из трейса:

```
You are the university special courses desk. Use the tools before answering; course ids come from spec_course_find. Answer briefly.
Greet a student you already know by name. Save one fact per save_memory call; read them back with search_memories.
Student card: {"name": "Sasha", "program": "first-year master's in computer science", "interests": "LLMs and AI", "constraints": "no Monday courses"}
```

Три строки, и безусловна только первая: `MEMORY_RULES` и карточка добавляются в той же ветке `store is not None`, в которой `build_agent` привязывает тулы памяти.

Оговорка: запись на sc-02 из хода 2 этот ход не увидел. `ENROLLMENTS` живёт в RAM и умерла вместе с тем процессом, а факт «записана на LLM Agents» модель в ходе 2 не сохранила (сохранила ограничение, но не запись) — и стол предложил записаться снова, честно показав 25 свободных мест. Эпизодическая память — это то, что модель сочла нужным сохранить, не больше.

## Тихий отказ: search как listing

`search_memories` передал запрос и получил всё:

```
запрос: {"query": "enrollments and interests"}
ответ:  Sasha transferred to the CS faculty.; Sasha is now a first-year master's student
        in computer science (previously applied math).; Sasha cannot attend courses on
        Mondays.; Sasha is interested in LLMs and AI generally.; Sasha is a second-year
        master's student in applied math.
```

Пять фактов на запрос о записях и интересах, свежие первыми, без score, с устаревшим «second-year applied math» в комплекте. `Store.search(query=...)` без настроенного индекса не ищет, а листает: ничего не бросает и не предупреждает. Ранжирование по смыслу появляется только с `index={"embed": ..., "dims": ...}`, а у этого стора индекса нет. Модель отфильтровала список сама — на пяти фактах работает, на пятисотах нет.

## Отравленный профиль: писатель, который обязан писать

`patch_profile` выполняется после каждого хода, а `tool_choice="Profile"` заставляет экстрактор вернуть документ всегда. На ходе без единого личного факта дешёвая модель обязана что-то выдать. Контрольный прогон — тот же юзер, тот же вопрос, пустой стор (`--store memory`, тред `visit-3`):

```
[tool] search_memories({'query': 'enrollments'})
[tool] search_memories({'query': 'student name and interests'})
...
nothing stored about this student yet
...
I don't have anything on file for you yet — could you tell me your name and what
you're into (subject or topic), and I'll pull up what's on the board?
```

Стол её не узнаёт — так и должно быть. А вот профиль, который такие ходы оставляют после себя, — стохастический мусор. Тот же прогон, повторённый вторым процессом, закончился строкой:

```
[profile] u-sasha: {"name": "Marisol", "program": null, "interests": null, "constraints": null}
```

Выдуманное имя из пустоты. Ход на другом юзере дал второй исход — четыре `null` (`[profile] u-quiet: {"name": null, "program": null, "interests": null, "constraints": null}`), а ход «What special courses do you have this semester?» — третий: экстрактор запихал ответ тула в поле, `{"constraints": "Wednesday 19:00 is fine; no other constraints mentioned."}`. Информационно-пустой ход, три разных мусорных профиля.

`desk_prompt` отфильтровывает пустые поля и не печатает карточку из одних `null`, но выдуманное имя фильтром не останавливается. В sqlite-сторе такой профиль прилип бы: следующий ход поприветствовал бы «Marisol». В этом прогоне стор был in-memory и умер вместе с процессом — единственная причина, почему никто не пострадал.

Куда смотреть за решением: коллекция фактов через `create_extractor(..., enable_inserts=True)` (ноутбук, cells 27–28) решает «сохранять ли вообще» — вставка опциональна, можно ничего не вставить; одиночный `Profile` с `tool_choice` этого выбора не имеет. Задокументировано как ловушка, не исправлено: это честная цена фонового писателя в текущей схеме.

## Трейс

`runs/session-05-trace.json` — recognition-ход диалога два, 29 наблюдений, 4 генерации.

| генерация | где в дереве | вход / выход |
|---|---|---:|
| модельный вызов 1: карточка, `search_memories` + `spec_course_find` | `model` | 739 / 93 |
| модельный вызов 2: `spec_course_info` ×2 | `model` | 924 / 76 |
| модельный вызов 3: ответ | `model` | 1067 / 122 |
| trustcall-извлечение | `patch_profile.after_agent` > `TrustCall` > `extract_updates` | 2158 / 160 |

Вход вызова — системный промпт, сообщения и схемы всех пяти тулов, поэтому даже первый вызов свежего треда весит 739 токенов, а не полторы сотни. История растёт от вызова к вызову: 739 → 924 → 1067.

Четыре `TOOL`-спана: `search_memories`, `spec_course_find`, `spec_course_info` ×2.

Четвёртая генерация — фоновой писатель, тарифицируется отдельно и после того, как ответ уже ушёл: 2158 входных токенов сверх 2730 у трёх вызовов самого хода, +79% к входу хода. Её промпт — не промпт стола, а `PROFILE_RULE` + trustcall-обёртка JSON Patch поверх `existing`:

```
Fill the profile from the student speaking only, never from a name enrolled for someone else.

Generate JSONPatches to update the existing schema instances.
<existing>
<schema id=Profile>
<instance>
{'name': 'Sasha', 'program': "first-year master's in computer science", 'interests': 'LLMs and AI', 'constraints': 'no Monday courses'}
</instance>
```

Ответ экстрактора на этом ходу: тулколл `Profile` с теми же четырьмя полями без изменений — ход не научил стол ничему новому, и ничего не изменилось.

Порядок в графе: ответ → `patch_profile.after_agent` → `summarize.after_agent` → конец; фоновой писатель успевает до свёртки. Часов в этом стеке Langfuse нет — все таймстемпы в API `9999-12-31T23:59:59` (тот же квирк, что в экспорте session 4), поэтому порядок наблюдений в файле — обход дерева от корня, а не сортировка по времени.

## Stretch: store переживает процесс

Стор живёт в `memory.db` (в `.gitignore`, как `assistant.db`). Процесс, который ни разу не говорит с моделью, открывает только файл:

```
uv run python -c "
from run import build_store
store = build_store()
print('profile :', store.get(('profiles', 'u-sasha'), 'profile').value)
for hit in store.search(('memories', 'u-sasha')):
    print('memory  :', hit.key, hit.value['fact'], '|', hit.created_at)
"
```

```
profile : {'name': 'Sasha', 'program': "first-year master's in computer science", 'interests': 'LLMs and AI', 'constraints': 'no Monday courses'}
memory  : 63229249 Sasha transferred to the CS faculty. | 2026-11-02 07:44:02
memory  : 19fb8118 Sasha is now a first-year master's student in computer science (previously applied math). | 2026-11-02 07:44:02
memory  : 37a79b17 Sasha cannot attend courses on Mondays. | 2026-11-02 07:43:14
memory  : 7948c11a Sasha is interested in LLMs and AI generally. | 2026-11-02 07:42:37
memory  : cd28a71c Sasha is a second-year master's student in applied math. | 2026-11-02 07:42:37
```

`created_at` по убыванию — это и есть порядок, в котором диалог два получил список фактов: самые свежие первыми. Профиль и все пять фактов пережили четыре процесса; `memory.db` — единственная связь между ними.

Контроль с `--store memory` — уже выше: тот же `u-sasha`, тот же вопрос, пустой стор — стол спрашивает имя. Long-term память, не переживающая процесс, — это short-term с лишними шагами. InMemoryStore → SqliteStore — тот же ход на полку выше, что InMemorySaver → SqliteSaver в session 4; session 8 сделает его ещё раз, до Postgres.

## Сегодня в одной карточке

По классификации ноутбука, для этого агента:

- **semantic** — профиль: имя, программа, интересы, ограничения. `("profiles", user_id)`, фоновой писатель (trustcall-патч после хода).
- **episodic** — факты: «перевелась на CS», «не по понедельникам», «записана на LLM Agents». `("memories", user_id)`, горячий путь (`save_memory`), один факт на запись.
- **procedural** — как вести себя столу (`MEMORY_RULES`) — в системном промпте, не в сторе; ограничение студента «no Monday courses» — по форме semantic-поле, по употреблению правило.

Две ловушки дня, обе пойманы на живом агенте: `search(query=...)` без индекса — это listing без score и предупреждений; экстрактор с `tool_choice="Profile"` обязан вернуть документ — на ходе без фактов он выдумает имя, запишет четыре `null` или утянет ответ тула в профиль.
