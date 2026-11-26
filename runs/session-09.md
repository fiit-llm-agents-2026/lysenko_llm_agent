# Session 09 — исследователь спецкурсов

**Вопрос:** Which special courses should the university recommend to students interested in AI who cannot attend before 16:00, and where do schedule or seat limits constrain the alternatives?

Архитектура: оркестратор с приватными подграфами интервью, потому что аналитики могут проверять разные аспекты одновременно, а отчёту нужны все секции.

Поиск: 7 локальных документов, без сети. Лимит графа: 36.

## Команда до правки

- Dr. Amara Osei — Curriculum and degree-requirements specialist who maps AI course sequences, prerequisites, and which electives actually count toward the AI concentration
- Priya Ramanathan — Registrar and scheduling analyst who models time-conflict constraints, section offerings after 16:00, and enrollment caps that block otherwise-eligible students
- Marcus Bell — Working student and accessibility advocate who represents students with jobs, commutes, or caregiving duties and evaluates whether recommended courses are realistically attendable
- Dr. Elena Vasquez — AI faculty member and industry-pipeline advisor who judges which special courses build genuinely marketable AI skills and where demand outstrips seat supply

**Правка редактора:** Include a commuter student advocate focused on evening attendance.

## Команда после правки

- Dr. Amara Osei — Curriculum and AI course-sequencing expert who maps which special courses actually build AI competency and prerequisites
- Luis Ferrer — Commuter student advocate focused on evening attendance, transit-dependent schedules, and late-day course availability
- Priya Raman — Registrar and enrollment data analyst who tracks seat caps, waitlists, room capacity, and time-block bottlenecks
- Prof. Daniel Whitfield — Faculty workload and scheduling realist who knows which courses can realistically be offered after 16:00 and what staffing constraints apply

## Сводный отчёт

**Рекомендация:** для интересующихся AI и недоступных до 16:00 подходит только sc-02 LLM Agents (пятница, 16:30, ауд. 412, 25 мест) [Doc 2]; sc-03 Computer Vision идёт в 14:00 [Doc 3]. Сначала проверяйте время [Doc 6].

**Компромиссы:** sc-01 и sc-04 тоже после 16:00, но не AI [Doc 1][Doc 4]; у sc-04 всего 3 места [Doc 4].

**Ограничения доказательств:** вместимость — не текущее наличие мест [Doc 7]; предварительные требования, листы ожидания и альтернативные секции не указаны [Doc 2].

## Solo: тот же корпус за один вызов

**Рекомендация:** студентам, интересующимся ИИ и не имеющим возможности посещать занятия до 16:00, следует рекомендовать sc-02 «LLM Agents» (пятница, 16:30) — единственный курс с тегами «ai» среди доступных после 16:00 [Doc 2; Doc 6]. Альтернатива — sc-01, но он не по теме ИИ [Doc 1].

**Компромиссы:** sc-04 подходит по времени, но имеет лишь 3 места и не относится к ИИ [Doc 4]. sc-03 и sc-05 тематически релевантны, но начинаются до 16:00 [Doc 3; Doc 5].

**Ограничения доказательств:** указана лишь каталожная ёмкость, а не фактическое наличие мест; перед записью необходимо проверить свободные места [Doc 7].

## Стоимость в токенах

Данные из `usageDetails` поколений в Langfuse; в Team включены оба состава аналитиков.

| Режим | Вызовы модели | Входные токены | Выходные токены | Всего |
|---|---:|---:|---:|---:|
| Solo | 1 | 377 | 210 | 587 |
| Team | 23 | 7665 | 2290 | 9955 |

## Трасса

- Team: `83dd8de729386bb0dca55723fc056532`
- Solo: `fd49816aeb3581b22857b41cc18712c1`
- Экспорт: [session-09-trace.json](session-09-trace.json)

Интервью — сестринские наблюдения с общим родителем `fe057143c5638569`; их интервалы попарно пересекаются:

| Наблюдение | Начало (UTC) | Конец (UTC) |
|---|---|---|
| `1e69f2be27ede5a9` | 2026-11-26T14:01:55.683329+00:00 | 2026-11-26T14:02:08.629259+00:00 |
| `8a8df1bf61cf8076` | 2026-11-26T14:01:55.684163+00:00 | 2026-11-26T14:02:12.816671+00:00 |
| `55a66331f4e09664` | 2026-11-26T14:01:55.684894+00:00 | 2026-11-26T14:02:09.724914+00:00 |
| `1c856373a86e3d08` | 2026-11-26T14:01:55.688368+00:00 | 2026-11-26T14:02:09.215746+00:00 |
