import json
import os
import sqlite3
import sys
from functools import cache
from typing import NotRequired

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentState, after_agent, dynamic_prompt, wrap_tool_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError

load_dotenv()


def chat_model(size: str = "cheap", **kwargs):
    name = os.environ[f"MODEL_{size.upper()}"]
    secret = os.environ["LLM_API_KEY"]
    if os.getenv("LLM_REASONING_EFFORT"):
        kwargs.setdefault("reasoning_effort", os.environ["LLM_REASONING_EFFORT"])
    if os.getenv("LLM_PROVIDER", "openai_compat") == "google_genai":
        return init_chat_model(f"google_genai:{name}", api_key=secret, **kwargs)
    return init_chat_model(
        f"openai:{name}", api_key=secret, base_url=os.environ["LLM_BASE_URL"], **kwargs
    )


SPEC_COURSES = {
    "sc-01": {"title": "Chill Course", "tags": "chill, relax", "day": "Tuesday",
              "time": "18:00", "room": "Room 105", "teacher": "A. Petrov", "seats": 15},
    "sc-02": {"title": "LLM Agents", "tags": "llm, ai, agents", "day": "Friday",
              "time": "16:30", "room": "Room 412", "teacher": "I. Smirnov", "seats": 25},
    "sc-03": {"title": "Computer Vision", "tags": "ai, images, cv", "day": "Monday",
              "time": "14:00", "room": "Room 301", "teacher": "E. Volkova", "seats": 20},
    "sc-04": {"title": "Board Game Theory", "tags": "games, math, chill", "day": "Wednesday",
              "time": "19:00", "room": "Student club", "teacher": "D. Orlov", "seats": 3},
    "sc-05": {"title": "Functional Programming", "tags": "haskell, math, coding", "day": "Thursday",
              "time": "12:00", "room": "Room 214", "teacher": "M. Kuznetsova", "seats": 30},
}
ENROLLMENTS: dict[str, list[str]] = {}


def _tags(course: dict) -> set[str]:
    return {t.strip() for t in course["tags"].split(",")}


def _free_seats(course_id: str) -> int:
    return SPEC_COURSES[course_id]["seats"] - len(ENROLLMENTS.get(course_id, []))


@tool(parse_docstring=True)
def spec_course_find(query: str) -> str:
    """Find university special courses by one word.

    Args:
        query: A title word, a topic tag or a weekday, for example 'ai' or 'friday'. Returns course ids for spec_course_info and spec_course_enroll.
    """
    needle = query.strip().lower()
    hits = [(i, c) for i, c in SPEC_COURSES.items()
            if needle in c["title"].lower().split() or needle in _tags(c) or needle == c["day"].lower()]
    if not hits:
        tags = sorted({t for c in SPEC_COURSES.values() for t in _tags(c)})
        return f"No course matching {query!r}. Try a weekday or one topic word: {', '.join(tags)}."
    return "; ".join(f"{i}: {c['title']}" for i, c in hits)


@tool(parse_docstring=True)
def spec_course_info(course_id: str) -> str:
    """Show the schedule, room, teacher and free seats of one course.

    Args:
        course_id: A course id from spec_course_find, for example 'sc-01'.
    """
    key = course_id.strip().lower()
    course = SPEC_COURSES.get(key)
    if course is None:
        return f"No course {course_id!r}. Call spec_course_find first to get a valid id."
    return (f"{course['title']}: {course['day']} {course['time']}, {course['room']}, "
            f"teacher {course['teacher']}, {_free_seats(key)} seats free.")


@tool(parse_docstring=True)
def spec_course_enroll(course_id: str, student: str) -> str:
    """Enroll the named student in one course.

    Args:
        course_id: A course id from spec_course_find, for example 'sc-02'.
        student: Name of the student to enroll.
    """
    key = course_id.strip().lower()
    course = SPEC_COURSES.get(key)
    if course is None:
        return f"No course {course_id!r}. Call spec_course_find first to get a valid id."
    taken = ENROLLMENTS.setdefault(key, [])
    if student in taken:
        return f"{student} is already enrolled in {course['title']}."
    if _free_seats(key) <= 0:
        return f"{course['title']} is full. Suggest another course from spec_course_find."
    taken.append(student)
    return f"Enrolled {student} in {course['title']}. {_free_seats(key)} seats left."


TOOLS = [spec_course_find, spec_course_info, spec_course_enroll]
SYSTEM = ("You are the university special courses desk. Use the tools before answering; "
          "course ids come from spec_course_find. Answer briefly.")


@wrap_tool_call
def log_tool_call(request, handler):
    print(f"[tool] {request.tool_call['name']}({request.tool_call['args']})")
    return handler(request)


class CoursesState(AgentState):
    summary: NotRequired[str]


SUMMARY_AFTER = 20


@cache
def cheap_model():
    return chat_model("cheap")


@dynamic_prompt
def prompt_with_summary(request) -> str:
    summary = request.state.get("summary")
    return f"{SYSTEM}\nSummary of the dialogue so far: {summary}" if summary else SYSTEM


def last_turn(messages: list) -> list:
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[start:]


@after_agent(state_schema=CoursesState)
def summarize(state, runtime) -> dict | None:
    messages = state["messages"]
    if len(messages) <= SUMMARY_AFTER:
        return None
    ask = HumanMessage("Fold the dialogue above into a short summary: the student's name and "
                       "personal facts, course ids and titles, enrollments made, decisions, "
                       "open questions.")
    prior = []
    if state.get("summary"):
        prior = [SystemMessage(f"Earlier summary: {state['summary']}")]
    digest = cheap_model().invoke(prior + messages + [ask])
    keep = len(last_turn(messages))
    prune = [RemoveMessage(id=m.id) for m in messages[:-keep]]
    return {"summary": digest.text, "messages": prune}


def sqlite_checkpointer(path: str = "assistant.db") -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def build_agent(checkpointer=None, summarization: bool = True):
    memory = [prompt_with_summary, summarize] if summarization else []
    return create_agent(cheap_model(), TOOLS, system_prompt=SYSTEM, checkpointer=checkpointer,
                        middleware=[log_tool_call, *memory])


def print_schemas() -> None:
    for spec in TOOLS:
        print(f"### {spec.name}")
        print(json.dumps(convert_to_openai_tool(spec), indent=2))
        print()


def ask(agent, text: str, thread_id: str, callbacks: list | None = None) -> dict:
    return agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25,
                "callbacks": callbacks or []},
    )


def trace_callbacks() -> list:
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return []
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler

    try:
        up = get_client().auth_check()
    except Exception as error:
        up = type(error).__name__
    print("langfuse:", os.getenv("LANGFUSE_HOST"), "| up:", up)
    return [CallbackHandler()] if up is True else []


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--schemas" in args:
        print_schemas()
        raise SystemExit
    if "--mermaid" in args:
        print(build_agent().get_graph().draw_mermaid())
        raise SystemExit
    thread = "desk"
    if "--thread" in args:
        at = args.index("--thread")
        if at + 1 >= len(args):
            raise SystemExit("--thread needs a name")
        thread = args.pop(at + 1)
        args.pop(at)
    agent = build_agent(sqlite_checkpointer())
    question = " ".join(args) or "What course can I take just to relax? Enroll me as Sasha."
    callbacks = trace_callbacks()
    try:
        state = ask(agent, question, thread, callbacks)
        for message in last_turn(state["messages"]):
            message.pretty_print()
        summary = state.get("summary", "")
        print(f"[state] thread={thread} | {len(state['messages'])} messages | summary: "
              f"{summary[:80] + '...' if summary else 'none yet'}")
    except GraphRecursionError:
        print("Stopped: the agent hit the step limit without a final answer.")
    if callbacks:
        from langfuse import get_client

        get_client().flush()
