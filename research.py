import argparse
import json
import operator
import re
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Annotated, TypedDict
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field

from run import SPEC_COURSES, chat_model

TOPIC = (
    "Which special courses should the university recommend to students interested in AI "
    "who cannot attend before 16:00, and where do schedule or seat limits constrain the alternatives?"
)
EARLIEST_START = "16:00"
TURNS = 2
MAX_ANALYSTS = 4
RECURSION_LIMIT = 8 + MAX_ANALYSTS * (3 * TURNS + 1)
CORPUS = {
    **{
        f"Doc {index}": (
            f"Catalog: {course_id} {course['title']} ({course['tags']}), "
            f"{course['day']} at {course['time']}, {course['room']}; "
            f"teacher {course['teacher']}; capacity {course['seats']} seats."
        )
        for index, (course_id, course) in enumerate(SPEC_COURSES.items(), start=1)
    },
    "Doc 6": f"Advising brief: screen against the earliest start of {EARLIEST_START} before ranking topical fit.",
    "Doc 7": "Enrollment policy: catalog capacity is not live availability. Confirm open seats before enrollment.",
}
CATALOG_SOURCES = "\n".join(f"[{doc_id}] {text}" for doc_id, text in CORPUS.items())
CATALOG_FACTS = (
    f"The catalog contains {len(SPEC_COURSES)} courses. "
    f"Courses starting at or after {EARLIEST_START}: "
    + ", ".join(course_id for course_id, course in SPEC_COURSES.items() if course["time"] >= EARLIEST_START)
    + "."
)
SEARCH_SCOPE = (
    "These are search excerpts, not the full catalog. "
    "Do not infer catalog size or rule out courses from missing excerpts."
)
STOP_WORDS = frozenset(
    "about after before course courses could does have know most should that their them there these they "
    "this those university what when where which will with would".split()
)
REPORT_INSTRUCTIONS = (
    "Write a Russian report in at most 120 words: recommendation, trade-offs and evidence limits. "
    "Cite only supplied evidence as [Doc N]; distinguish catalog capacity from live availability. "
    "The full catalog and computed facts take precedence over any interview summaries."
)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


DOCUMENT_TERMS = {doc_id: tokens(text) for doc_id, text in CORPUS.items()}


def stub_search(query: str) -> str:
    terms = {term for term in tokens(query) if len(term) >= 3 or term in {"ai", "cv"}} - STOP_WORDS
    scores = [(len(terms & words), doc_id) for doc_id, words in DOCUMENT_TERMS.items()]
    hits = [f"[{doc_id}] {CORPUS[doc_id]}" for score, doc_id in sorted(scores, key=lambda item: -item[0])[:3] if score]
    return "\n".join(hits) or "No documents matched. Try catalog terms like AI, Friday, capacity or enrollment."


class Analyst(BaseModel):
    name: str = Field(description="Short persona name")
    role: str = Field(description="Distinct perspective this analyst represents")


class Perspectives(BaseModel):
    analysts: list[Analyst] = Field(min_length=3, max_length=MAX_ANALYSTS)


class InterviewState(TypedDict):
    topic: str
    analyst: dict[str, str]
    messages: Annotated[list[BaseMessage], add_messages]
    docs: Annotated[list[str], operator.add]
    turns: int
    sections: Annotated[list[str], operator.add]


class InterviewOutput(TypedDict):
    sections: Annotated[list[str], operator.add]


class ResearchState(TypedDict):
    topic: str
    feedback: str
    analysts: list[dict[str, str]]
    sections: Annotated[list[str], operator.add]
    report: str


def build_research(analyst_model, interview_model, report_model):
    structured = analyst_model.with_structured_output(Perspectives, method="function_calling")

    def ask_question(state: InterviewState, config: RunnableConfig) -> dict:
        analyst = state["analyst"]
        prompt = (
            f"You are {analyst['name']}, representing {analyst['role']}. "
            f"Ask one short question in English on {state['topic']} using specific catalog terms. "
            "If there is already an answer, explore a different aspect. "
            "Do not assume any course, prerequisite, or section exists without evidence."
        )
        return {"messages": [interview_model.invoke([SystemMessage(prompt), *state["messages"]], config)]}

    def search_docs(state: InterviewState) -> dict:
        return {"docs": [stub_search(state["messages"][-1].text)]}

    def answer_question(state: InterviewState, config: RunnableConfig) -> dict:
        prompt = (
            "Answer the latest question in English in one sentence using the sources below. "
            f"Cite [Doc N]. Say when the answer is unknown. {SEARCH_SCOPE}\n" + state["docs"][-1]
        )
        question = HumanMessage(state["messages"][-1].text)
        answer = interview_model.invoke([SystemMessage(prompt), question], config)
        return {"messages": [HumanMessage(answer.text)], "turns": state["turns"] + 1}

    def route_turn(state: InterviewState) -> str:
        return "ask_question" if state["turns"] < TURNS else "write_section"

    def write_section(state: InterviewState, config: RunnableConfig) -> dict:
        prompt = (
            f"Summarize the perspective of {state['analyst']['name']} in two short Russian sentences. "
            f"Preserve [Doc N] citations and do not introduce new facts. {SEARCH_SCOPE}\n"
            + "\n".join(state["docs"])
        )
        transcript = "\n".join(f"{message.type}: {message.text}" for message in state["messages"][1:])
        reply = interview_model.invoke([SystemMessage(prompt), HumanMessage(transcript)], config)
        return {"sections": [f"{state['analyst']['name']}: {reply.text}"]}

    child = StateGraph(InterviewState, output_schema=InterviewOutput)
    child.add_node("ask_question", ask_question)
    child.add_node("search_docs", search_docs)
    child.add_node("answer_question", answer_question)
    child.add_node("write_section", write_section)
    child.add_edge(START, "ask_question")
    child.add_edge("ask_question", "search_docs")
    child.add_edge("search_docs", "answer_question")
    child.add_conditional_edges("answer_question", route_turn, ["ask_question", "write_section"])
    child.add_edge("write_section", END)

    def create_analysts(state: ResearchState, config: RunnableConfig) -> dict:
        prompt = (
            f"Pick three or four analysts with distinct perspectives for: {state['topic']}\n"
            f"Editor feedback to incorporate: {state['feedback'] or 'none'}."
        )
        team = structured.invoke(prompt, config)
        return {"analysts": [analyst.model_dump() for analyst in team.analysts]}

    def review_team(state: ResearchState) -> dict:
        decision = interrupt({"team": state["analysts"], "hint": "Send feedback or approve."})
        return {"feedback": decision.strip()}

    def route_team(state: ResearchState) -> str | list[Send]:
        if state["feedback"].casefold() != "approve":
            return "create_analysts"
        return [
            Send("interview", {
                "topic": state["topic"], "analyst": analyst,
                "messages": [HumanMessage(f"Interview focus: {state['topic']}")], "turns": 0,
            })
            for analyst in state["analysts"]
        ]

    def write_report(state: ResearchState, config: RunnableConfig) -> dict:
        sections = "\n\n".join(state["sections"])
        prompt = (
            f"{REPORT_INSTRUCTIONS}\nTopic: {state['topic']}\n"
            f"Catalog facts: {CATALOG_FACTS}\nCatalog and policy sources:\n{CATALOG_SOURCES}\n"
            f"Interview sections:\n{sections}"
        )
        return {"report": report_model.invoke(prompt, config).text}

    parent = StateGraph(ResearchState)
    parent.add_node("create_analysts", create_analysts)
    parent.add_node("review_team", review_team)
    parent.add_node("interview", child.compile(name="interview"))
    parent.add_node("write_report", write_report)
    parent.add_edge(START, "create_analysts")
    parent.add_edge("create_analysts", "review_team")
    parent.add_conditional_edges("review_team", route_team, ["create_analysts", "interview"])
    parent.add_edge("interview", "write_report")
    parent.add_edge("write_report", END)
    return parent.compile(checkpointer=InMemorySaver(), name="research")


def export_trace(spans, trace_id: str, expected_calls: int) -> dict:
    observations = []
    for span in spans:
        if f"{span.context.trace_id:032x}" != trace_id:
            continue
        attrs = span.attributes
        prefix = "langfuse.observation."
        observations.append({
            "id": f"{span.context.span_id:016x}",
            "parentObservationId": f"{span.parent.span_id:016x}" if span.parent else None,
            "name": span.name,
            "type": attrs[prefix + "type"].upper(),
            "startTime": datetime.fromtimestamp(span.start_time / 1e9, UTC).isoformat(),
            "endTime": datetime.fromtimestamp(span.end_time / 1e9, UTC).isoformat(),
            "model": attrs.get(prefix + "model.name"),
            "usageDetails": json.loads(attrs.get(prefix + "usage_details", "{}")),
            "input": attrs.get(prefix + "input"),
            "output": attrs.get(prefix + "output"),
        })
    runs = [item for item in observations if item["type"] == "GENERATION"]
    if len(runs) != expected_calls or any({"input", "output"} - item["usageDetails"].keys() for item in runs):
        raise RuntimeError(f"Langfuse did not export {expected_calls} generations with usage for {trace_id}")
    return {"id": trace_id, "observations": sorted(observations, key=lambda item: item["startTime"])}


def usage(trace: dict) -> tuple[int, int, int]:
    generations = [item["usageDetails"] for item in trace["observations"] if item["type"] == "GENERATION"]
    return len(generations), sum(item["input"] for item in generations), sum(item["output"] for item in generations)


def parallel_interviews(trace: dict, count: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in trace["observations"]:
        if item["name"] == "interview" and item.get("parentObservationId") and item.get("endTime"):
            groups.setdefault(item["parentObservationId"], []).append(item)
    for siblings in groups.values():
        if len(siblings) != count:
            continue
        intervals = [
            (datetime.fromisoformat(item["startTime"]), datetime.fromisoformat(item["endTime"]))
            for item in siblings
        ]
        if all(max(a[0], b[0]) < min(a[1], b[1]) for a, b in combinations(intervals, 2)):
            return sorted(siblings, key=lambda item: item["startTime"])
    raise RuntimeError("Langfuse trace does not show overlapping sibling interviews")


def save_run(output_dir: Path, feedback: str, before: dict, after: dict, done: dict,
             solo_report: str, team_trace: dict, solo_trace: dict) -> None:
    branches = parallel_interviews(team_trace, len(done["analysts"]))
    lines = [
        "# Session 09 — исследователь спецкурсов", "", f"**Вопрос:** {TOPIC}", "",
        "Архитектура: оркестратор с приватными подграфами интервью, потому что аналитики могут "
        "проверять разные аспекты одновременно, а отчёту нужны все секции.", "",
        f"Поиск: {len(CORPUS)} локальных документов, без сети. Лимит графа: {RECURSION_LIMIT}.", "",
        "## Команда до правки", "",
        *(f"- {a['name']} — {a['role']}" for a in before["analysts"]), "",
        f"**Правка редактора:** {feedback}", "", "## Команда после правки", "",
        *(f"- {a['name']} — {a['role']}" for a in after["analysts"]), "",
        "## Сводный отчёт", "", done["report"], "", "## Solo: тот же корпус за один вызов", "", solo_report, "",
        "## Стоимость в токенах", "",
        "Данные из `usageDetails` поколений в Langfuse; в Team включены оба состава аналитиков.", "",
        "| Режим | Вызовы модели | Входные токены | Выходные токены | Всего |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, trace in [("Solo", solo_trace), ("Team", team_trace)]:
        calls, input_tokens, output_tokens = usage(trace)
        lines.append(f"| {label} | {calls} | {input_tokens} | {output_tokens} | {input_tokens + output_tokens} |")
    lines += [
        "", "## Трасса", "", f"- Team: `{team_trace['id']}`", f"- Solo: `{solo_trace['id']}`",
        "- Экспорт: [session-09-trace.json](session-09-trace.json)", "",
        f"Интервью — сестринские наблюдения с общим родителем `{branches[0]['parentObservationId']}`; "
        "их интервалы попарно пересекаются:", "",
        "| Наблюдение | Начало (UTC) | Конец (UTC) |", "|---|---|---|",
        *(f"| `{item['id']}` | {item['startTime']} | {item['endTime']} |" for item in branches), "",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "session-09-trace.json").write_text(
        json.dumps({"team": team_trace, "solo": solo_trace}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "session-09.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    parser = argparse.ArgumentParser(description="Research the special-course catalog and export the traced run.")
    parser.add_argument("--feedback", required=True, help="Editorial instruction for the revised analyst team.")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    feedback = args.feedback.strip()
    if not feedback or feedback.casefold() == "approve":
        parser.error("--feedback must request a change to the team")
    exporter = InMemorySpanExporter()
    local_key = "session-09-local"
    client = Langfuse(public_key=local_key, secret_key=local_key, tracer_provider=TracerProvider(),
                      span_exporter=exporter)
    handler = CallbackHandler(public_key=local_key)

    cheap = chat_model("cheap", temperature=0)
    strong = chat_model("strong", temperature=0)
    research = build_research(strong, cheap, strong)
    config: RunnableConfig = {
        "configurable": {"thread_id": uuid4().hex}, "recursion_limit": RECURSION_LIMIT,
        "callbacks": [handler], "max_concurrency": MAX_ANALYSTS,
    }
    with client.start_as_current_observation(name="session-09-team", as_type="span") as team:
        before = research.invoke({"topic": TOPIC, "feedback": ""}, config)
        after = research.invoke(Command(resume=feedback), config)
        done = research.invoke(Command(resume="approve"), config)
        team.update(output=done["report"])

    with client.start_as_current_observation(name="session-09-solo", as_type="span") as solo:
        prompt = (
            f"{REPORT_INSTRUCTIONS}\nTopic: {TOPIC}\n"
            f"Catalog facts: {CATALOG_FACTS}\nCatalog and policy sources:\n{CATALOG_SOURCES}"
        )
        solo_report = strong.invoke(prompt, {"recursion_limit": RECURSION_LIMIT, "callbacks": [handler]}).text
        solo.update(output=solo_report)

    client.flush()
    calls = 3 + len(done["analysts"]) * (2 * TURNS + 1)
    print(f"Langfuse team: {team.trace_id}\nLangfuse solo: {solo.trace_id}", flush=True)
    spans = exporter.get_finished_spans()
    team_trace = export_trace(spans, team.trace_id, calls)
    solo_trace = export_trace(spans, solo.trace_id, 1)
    save_run(args.output_dir, feedback, before, after, done, solo_report, team_trace, solo_trace)
    print(f"Report and trace written to {args.output_dir}")


if __name__ == "__main__":
    main()
