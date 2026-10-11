import json
import os
import sys

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
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


def build_agent():
    return create_agent(chat_model("cheap"), TOOLS, system_prompt=SYSTEM,
                        middleware=[log_tool_call])


def print_schemas() -> None:
    for spec in TOOLS:
        print(f"### {spec.name}")
        print(json.dumps(convert_to_openai_tool(spec), indent=2))
        print()


def ask(agent, text: str, callbacks: list | None = None) -> list:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config={"recursion_limit": 12, "callbacks": callbacks or []},
    )
    return result["messages"]


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
    if "--schemas" in sys.argv:
        print_schemas()
        raise SystemExit
    agent = build_agent()
    if "--mermaid" in sys.argv:
        print(agent.get_graph().draw_mermaid())
        raise SystemExit
    question = " ".join(sys.argv[1:]) or "What course can I take just to relax? Enroll me as Sasha."
    callbacks = trace_callbacks()
    try:
        for message in ask(agent, question, callbacks):
            message.pretty_print()
    except GraphRecursionError:
        print("Stopped: the agent hit the step limit without a final answer.")
    if callbacks:
        from langfuse import get_client

        get_client().flush()
