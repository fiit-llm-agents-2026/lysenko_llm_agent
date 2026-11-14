# Session 6: стриминг и human-in-the-loop — гейт на запись, консольный клиент, две ветки

Практика ноутбука: закрыть подтверждением самый опасный инструмент собственного агента, сделать консольный клиент со стримингом и `input()`, воспроизвести ловушку с ресумом без чекпоинтера и оставить две ветки одного диалога.

В этом репозитории опасный инструмент один: `spec_course_enroll`. `spec_course_find` и `spec_course_info` только читают каталог, а `spec_course_enroll` меняет `ENROLLMENTS` — записывает студента на спецкурс, и отменить это нечем. На нём и стоит гейт.

## Что изменилось

`run.py`:

- `GATED = {"spec_course_enroll": True}` — политика подтверждения;
- у `build_agent(checkpointer, summarization, store, approvals)` появился параметр `approvals`; если он передан, в middleware добавляется `HumanInTheLoopMiddleware(interrupt_on=approvals)`.

Гейт включается только там, где есть человек:

```python
agent = build_agent(
    sqlite_checkpointer(),
    store=None,
    approvals=GATED,
)
```

`run.py` и `load_test.py` вызывают `build_agent` без `approvals`: батчевые прогоны остаются автоматическими, как и записано в `PROPOSAL.md` («в интерактивном демо деструктивные операции требуют подтверждения, в экспериментах выполняются автоматически»).

`chat.py` — новый консольный клиент:

- `stream_mode=["messages", "updates"]`;
- токены модели печатаются из `("messages", ...)`, ответы инструментов — из `("updates", ...)`;
- `{"__interrupt__": ...}` показывает `action_requests` и `review_configs`, спрашивает `input()` и продолжает `Command(resume={"decisions": [...]})`;
- поддерживает все четыре решения middleware: `approve`, `edit`, `reject`, `respond`;
- при старте проверяет `get_state()` и подхватывает паузу, оставшуюся от прошлого процесса;
- на каждый стрим создаёт свежий `CallbackHandler` и печатает его `last_trace_id`.

`fork.py` — time travel из консоли:

- `--list` печатает историю чекпоинтов: шаг, `next`, id, родителя, число сообщений и признак висящего гейта;
- `--at <checkpoint_id> --decision approve|edit|reject` проигрывает тред от указанной точки;
- два запуска с разными решениями оставляют в одном треде две ветки.

`README.md` получил раздел с запуском клиента и форка.

## Как выглядит граф с гейтом

Без `approvals` граф прежний: `model ⇄ tools`, после ответа — хуки `patch_profile` / `summarize`. С гейтом между моделью и инструментами появляется отдельный узел:

```
model --> HumanInTheLoopMiddleware.after_model
HumanInTheLoopMiddleware.after_model -.-> tools
HumanInTheLoopMiddleware.after_model -.-> model
```

Пауза — это `interrupt()` внутри `after_model`, а не исключение и не отдельный «режим ожидания». Пока человек не ответил, выполнение инструмента не начинается; сам `spec_course_enroll` остаётся обычным тулом без кода подтверждения внутри.

## Транскрипт: один отказ и одно одобрение

Тред `session-06`, пользователь `u-sasha`, `--store none`, чтобы в кадре не было фонового trustcall-экстрактора.

```
you> Enroll me as Sasha in Board Game Theory.
I'll find that course first.[tool] spec_course_find({'query': 'board'})

[spec_course_find] sc-04: Board Game Theory

[trace] 781ecf627009d13ec23ee048a8fd8515

[approval] spec_course_enroll {"course_id": "sc-04", "student": "Sasha"}
[allowed] approve, edit, reject, respond
approve / edit / reject / respond [a/e/r/s]: r
reason, empty means no reason: Wait, I only wanted the schedule, not an enrollment.
Understood — no enrollment made. Here's the schedule infoinstead:[tool] spec_course_info({'course_id': 'sc-04'})

[spec_course_info] Board Game Theory: Wednesday 19:00, Student club, teacher D. Orlov, 3 seats free.
**Board Game Theory (sc-04)**
- Wednesday, 19:00
- Room: Student club
- Teacher: D. Orlov
- Free seats: 3

Let me know if you'd like me to enroll you.
[trace] 623bda690f926359abf30fbddd1aa83d
[enrollments] {}

you> Okay, now enroll me as Sasha in Board Game Theory.

[trace] 52e1b17a17f9f81b3f43541b0654d15f

[approval] spec_course_enroll {"course_id": "sc-04", "student": "Sasha"}
[allowed] approve, edit, reject, respond
approve / edit / reject / respond [a/e/r/s]: a
[tool] spec_course_enroll({'course_id': 'sc-04', 'student': 'Sasha'})

[spec_course_enroll] Enrolled Sasha in Board Game Theory. 2 seats left.
Done — you're enrolled in **Board Game Theory** (sc-04). 2 seats left.
[trace] 53062cbb10e0991ad336a10b148f615f
[enrollments] {"sc-04": ["Sasha"]}

you> quit
```

Что здесь происходит по шагам:

1. Первый стрим доходит до `spec_course_enroll` и возвращает `{"__interrupt__": ...}`. В `ENROLLMENTS` пусто: `[enrollments] {}`.
2. Решение `reject` не запускает инструмент. Модель получает `ToolMessage` с отказом и причиной, после чего сама предлагает расписание через `spec_course_info`.
3. Второй ход снова доходит до того же гейта. Решение `approve` запускает `spec_course_enroll`; в `ENROLLMENTS` появляется ровно одна запись.
4. Побочный эффект инструмента находится после гейта по построению: middleware вызывает тул только после `approve`. Если бы запись шла до `interrupt()`, отказ всё равно оставил бы студента записанным.

Любопытная деталь: в отказе модель склеила два слова в `infoinstead:` — это её собственный текст, не артефакт стримера; в трейсе видно тот же дефект.

## Ловушка: пауза без чекпоинтера выглядит рабочей

Тот же агент, собранный без `checkpointer`:

```
paused: True
payload: {'course_id': 'sc-02', 'student': 'Sasha'}
RuntimeError: Cannot use Command(resume=...) without checkpointer
```

`invoke` возвращает `__interrupt__` и не падает: пауза «сработала». Но состояние паузы негде хранить, поэтому `Command(resume=...)` уже не находит, что продолжать. В клиенте чекпоинтер обязателен; `chat.py` всегда собирает агента с `sqlite_checkpointer()`.

## Пауза переживает процесс

Первый процесс останавливается на гейте и выходит по EOF:

```
[approval] spec_course_enroll {"course_id": "sc-05", "student": "Sasha"}
[allowed] approve, edit, reject, respond
approve / edit / reject / respond [a/e/r/s]:
[exit] no decision; the pause stays in the checkpointer
```

Второй процесс, тот же `--thread session-06-park`, начинает не с пустого места:

```
[parked] a gate from an earlier process is waiting in the checkpointer

[approval] spec_course_enroll {"course_id": "sc-05", "student": "Sasha"}
[allowed] approve, edit, reject, respond
approve / edit / reject / respond [a/e/r/s]: a
[spec_course_enroll] Enrolled Sasha in Functional Programming. 29 seats left.
```

Это то же свойство, что в ноутбуке: пауза живёт в `SqliteSaver`, а не на стеке Python. `assistant.db` — единственная связь между двумя процессами; без него второй процесс не увидел бы ни гейта, ни треда.

## Две ветки из одной точки

Диалог `session-06` уже содержит два гейта: отклонённый (`step 4`) и одобренный (`step 14`). Id родителя одобренного гейта находит `uv run python fork.py --thread session-06 --store none --list`; форкаем от чекпоинта `18d95640` (`step 13`, `next ('model',)`):

```
uv run python fork.py --thread session-06 --user u-sasha --store none --at 18d95640 --decision approve
[fork] step 13 | next ('model',) | checkpoint ..18d95640
[gate] [{"name": "spec_course_enroll", "args": {"course_id": "sc-04", "student": "Sasha"}, ...}]
[pause] checkpoint ..fd3b2fab
[tool] spec_course_enroll({'course_id': 'sc-04', 'student': 'Sasha'})
[decision] approve
[answer] Done — Sasha is enrolled in Board Game Theory (sc-04). 2 seats remain.
[enrollments] {"sc-04": ["Sasha"]}
[branch] checkpoint ..3a9f48cd
```

```
uv run python fork.py --thread session-06 --user u-sasha --store none --at 18d95640 --decision reject --reason 'I will confirm with my group first.'
[fork] step 13 | next ('model',) | checkpoint ..18d95640
[gate] [{"name": "spec_course_enroll", "args": {"course_id": "sc-04", "student": "Sasha"}, ...}]
[pause] checkpoint ..c466e3f5
[decision] reject
[answer] No problem — the enrollment wasn't submitted. Board Game Theory (sc-04) still has 3 seats free, so just ask again when your group confirms and I'll sign you up.
[enrollments] {}
[branch] checkpoint ..5dda845c
```

Обе ветки выросли из одного `18d95640`, но получили разные паузы (`fd3b2fab` и `c466e3f5`) и разные финалы. История после двух запусков:

```
  19  ()                                        5dda845c    bcf50cdb   12
  18  ('summarize.after_agent',)                 bcf50cdb    4d8f9120   12
  17  ('HumanInTheLoopMiddleware.after_model',)  4d8f9120    d34ad3d9   12
  16  ('model',)                                d34ad3d9    c466e3f5   11
  15  ('HumanInTheLoopMiddleware.after_model',)  c466e3f5    abe0076d   10  pending
  14  ('model',)                                abe0076d    18d95640    9

  20  ()                                        3a9f48cd    e5d93b21   12
  19  ('summarize.after_agent',)                e5d93b21    c454b2ae   12
  18  ('HumanInTheLoopMiddleware.after_model',)  c454b2ae    26fd81c0   12
  17  ('model',)                                26fd81c0    fdd24be2   11
  16  ('tools',)                                fdd24be2    fd3b2fab   10
  15  ('HumanInTheLoopMiddleware.after_model',)  fd3b2fab    0d2f0ab0   10  pending
  14  ('model',)                                0d2f0ab0    18d95640    9
```

Верхняя группа — ветка с отказом, нижняя — с одобрением; `step 14` в обеих ссылается на один родительский чекпоинт `18d95640`. Исходная ветка диалога тоже осталась в истории: время не перезаписывается, а дописывается.

Почему форк идёт от родителя паузы, а не от самой паузы: если взять один и тот же interrupt-чекпоинт и после первой ветки позвать `Command(resume=...)` ещё раз, вторая ветка подхватывает resume первой и выполняет инструмент, даже если решение было `reject`. Родитель паузы заставляет модель переиграть один шаг и создать каждой ветке собственный `interrupt` с собственным id. Цена — лишний вызов модели, поэтому аргументы веток могут теоретически разойтись; в этом прогоне обе ветки снова попросили `sc-04` для Sasha.

Отдельная честная оговорка: `ENROLLMENTS` — глобальный словарь процесса, а не часть состояния графа. `fork.py` очищает его перед каждой веткой, поэтому в выводе ветки изолированы. В реальной базе запись после `approve` никуда бы не откатилась: две ветки — это два будущих в чекпоинтере, а не транзакция над внешним стором. Для проекта это значит, что гейт защищает от лишнего вызова, но идемпотентность записи всё равно нужно проектировать отдельно.

## Трейс

`runs/session-06-trace.json` — экспорт трейса `53062cbb10e0991ad336a10b148f615f` из локального Langfuse. Это resume-прогон после `approve`, в нём виден сам опасный вызов:

| тип | имя | что внутри |
|---|---|---|
| CHAIN | `LangGraph` | корень трейса, input — `Command(resume={"decisions": [{"type": "approve"}]})` |
| CHAIN | `model` | шаг модели после решения |
| GENERATION | `ChatOpenAI` | 432 входных + 512 cache-read, 22 выходных токена |
| CHAIN | `tools` | узел инструментов |
| TOOL | `spec_course_enroll` | args `{course_id: sc-04, student: Sasha}`, output `Enrolled Sasha in Board Game Theory. 2 seats left.` |
| CHAIN | `HumanInTheLoopMiddleware.after_model` ×2 | гейт до и после выполнения |
| AGENT | `summarize.after_agent` | хук после ответа, ничего не меняет |

Всего 8 наблюдений. `session_id = session-06:session-06`, `user_id = u-sasha`, тег `session-06` — клиент выставляет их через `metadata` Langfuse, поэтому трейсы гейта легко отфильтровать от остальных прогонов.

Гейт оставляет не один трейс, а пару. В этом диалоге их четыре:

| прогон | trace id | генерации (вход / выход) | инструменты |
|---|---|---:|---|
| первый стрим до паузы | `781ecf627009d13ec23ee048a8fd8515` | 89/61 + 524/47, cache 512 | `spec_course_find` |
| resume с отказом | `623bda690f926359abf30fbddd1aa83d` | 267/52 + 688/55, cache 512 | `spec_course_info` |
| второй стрим до паузы | `52e1b17a17f9f81b3f43541b0654d15f` | 79/61, cache 768 | — |
| resume с одобрением | `53062cbb10e0991ad336a10b148f615f` | 432/22, cache 512 | `spec_course_enroll` |

Для артефакта достаточно resume-трейса: именно в нём `spec_course_enroll` виден как отдельный `TOOL`-спан. Пара «пауза + resume» рассказывает историю целиком: в первом трейсе нет выполнения инструмента, во втором есть.

По тарифам из session-03 весь диалог — примерно 2079 некэшированных входных, 2304 кэшевых и 298 выходных токенов, то есть около $0.0005 (≈ 0.05 цента). Стриминг на цену не влияет: это тот же объём токенов, просто отданный порциями.

## Stretch: решение `edit`

Клиент поддерживает `edit`, и это проверено отдельным тредом `session-06-edit`. Человек просил записать Tim, но на гейте заменил студента на Sasha:

```
[approval] spec_course_enroll {"course_id": "sc-04", "student": "Tim"}
[allowed] approve, edit, reject, respond
approve / edit / reject / respond [a/e/r/s]: e
new args as JSON, empty keeps them: {"course_id": "sc-04", "student": "Sasha"}
[tool] spec_course_enroll({'course_id': 'sc-04', 'student': 'Tim'})

[spec_course_enroll] Note: a human reviewer replaced this tool call before it ran. ... Executed instead: spec_course_enroll with arguments {"course_id": "sc-04", "student": "Sasha"}.

Tool response:
Enrolled Sasha in Board Game Theory. 2 seats left.
Done — though heads up: the enrollment that actually executed was for **Sasha**, not Tim.
[enrollments] {"sc-04": ["Sasha"]}
```

Middleware выполняет исправленный вызов и добавляет модели служебную заметку: записанный в сообщении tool call — не тот, что реально сработал, повторять исходный вызов не нужно. `[tool]`-лог при этом печатает исходные аргументы: `wrap_tool_call` видит вызов до подмены. Это ожидаемо и полезно знать при отладке.

## Сегодня в одной карточке

- Опасный инструмент закрыт `HumanInTheLoopMiddleware`, а не проверкой внутри тула: `interrupt_on={"spec_course_enroll": True}`. Пауза возвращает `action_requests` и `review_configs`; решение человека приходит в `Command(resume=...)`.
- Гейт без чекпоинтера выглядит рабочим ровно до первого resume: `__interrupt__` возвращается, а `Command(resume=...)` падает с `RuntimeError: Cannot use Command(resume=...) without checkpointer`.
- `SqliteSaver` держит паузу между процессами: второй запуск `chat.py` подхватывает чужой гейт по `thread_id`.
- Форк от родителя паузы даёт двум веткам собственные `interrupt`; обе ветки остаются в `get_state_history`, исходный диалог не перезаписывается.
- В трейсе гейт — это два прогона: пауза и resume. Approved-вызов виден в resume-трейсе; `runs/session-06-trace.json` — именно он.

**Для проекта:** подтверждение на `spec_course_enroll` — дешёвая security-мера к защите; стриминг заметно улучшает демо, потому что видно, как агент думает до гейта, а не только финальный ответ. Session 8 подключит этот же клиент к боту: пауза уже лежит в чекпоинтере, а не в памяти процесса, поэтому веб-процесс сможет продолжить её после перезапуска.
