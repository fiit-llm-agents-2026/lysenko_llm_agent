import json
import os
import sqlite3
import sys
import uuid
from functools import cache
from typing import NotRequired

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (AgentMiddleware, AgentState,
                                         HumanInTheLoopMiddleware, after_agent,
                                         dynamic_prompt)
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_config, get_store
from langgraph.errors import GraphRecursionError
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import SqliteStore
from pydantic import BaseModel, Field
from trustcall import create_extractor

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
GATED = {"spec_course_enroll": True}
SYSTEM = ("You are the university special courses desk. Use the tools before answering; "
          "course ids come from spec_course_find. Answer briefly.")
PROMPT_NAME = "special-courses-desk"
PROMPT_LABEL = "production"
LANGFUSE_USER = os.getenv("LANGFUSE_USER_ID") or "sany1111"


@cache
def prompt_source():
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None, SYSTEM
    try:
        from langfuse import get_client

        item = get_client().get_prompt(PROMPT_NAME, label=PROMPT_LABEL, type="text")
        return item, item.compile()
    except Exception as error:
        print(f"[prompt] fallback to local SYSTEM: {type(error).__name__}: {error}")
        return None, SYSTEM


def system_prompt() -> str:
    return prompt_source()[1]


def publish_prompt() -> None:
    from langfuse import get_client

    item = get_client().create_prompt(name=PROMPT_NAME, prompt=SYSTEM,
                                      labels=[PROMPT_LABEL], type="text")
    print(f"[prompt] {item.name} v{item.version} label {PROMPT_LABEL}")


def user_id() -> str:
    return get_config()["configurable"].get("user_id", "guest")


@tool(parse_docstring=True)
def save_memory(fact: str) -> str:
    """Store one durable fact about the student for future conversations.

    Args:
        fact: One fact in one short sentence, for example 'enrolled in LLM Agents in September'.
    """
    key = uuid.uuid4().hex[:8]
    get_store().put(("memories", user_id()), key, {"fact": fact})
    return f"saved as {key}"


@tool(parse_docstring=True)
def search_memories(query: str) -> str:
    """Look up facts stored about the student in earlier conversations.

    Args:
        query: What to look for, for example 'enrollments'.
    """
    hits = get_store().search(("memories", user_id()), limit=10)
    if not hits:
        return "nothing stored about this student yet"
    return "; ".join(hit.value["fact"] for hit in hits)


MEMORY_TOOLS = [save_memory, search_memories]
MEMORY_RULES = ("Greet a student you already know by name. Save one fact per "
                "save_memory call; read them back with search_memories.")


class LogToolCall(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        print(f"[tool] {request.tool_call['name']}({request.tool_call['args']})")
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        print(f"[tool] {request.tool_call['name']}({request.tool_call['args']})")
        return await handler(request)


log_tool_call = LogToolCall()


class CoursesState(AgentState):
    summary: NotRequired[str]


SUMMARY_AFTER = 20


@cache
def cheap_model():
    return chat_model("cheap")


class Profile(BaseModel):
    """What the special courses desk remembers about one student between conversations."""

    name: str | None = Field(None, description="First name of the student speaking, "
                             "never a name enrolled for someone else.")
    program: str | None = Field(None, description="Year and program of study, like "
                                "'second-year master's in applied math'.")
    interests: str | None = Field(None, description="Course topics the student likes.")
    constraints: str | None = Field(None, description="When the student cannot attend, "
                                    "like 'no Monday courses'.")


PROFILE_RULE = SystemMessage("Fill the profile from the student speaking only, never "
                             "from a name enrolled for someone else.")


@cache
def profile_extractor():
    return create_extractor(cheap_model(), tools=[Profile], tool_choice="Profile")


@dynamic_prompt
def desk_prompt(request) -> str:
    parts = [system_prompt()]
    store = request.runtime.store
    if store is not None:
        parts.append(MEMORY_RULES)
        item = store.get(("profiles", user_id()), "profile")
        card = {k: v for k, v in item.value.items() if v} if item else {}
        if card:
            parts.append(f"Student card: {json.dumps(card)}")
    if request.state.get("summary"):
        parts.append(f"Summary of the dialogue so far: {request.state['summary']}")
    return "\n".join(parts)


def last_turn(messages: list) -> list:
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[start:]


def make_summarize(model):
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
        digest = model.invoke(prior + messages + [ask])
        keep = len(last_turn(messages))
        prune = [RemoveMessage(id=m.id) for m in messages[:-keep]]
        return {"summary": digest.text, "messages": prune}

    return summarize


@after_agent
def patch_profile(state, runtime) -> None:
    namespace = ("profiles", user_id())
    item = runtime.store.get(namespace, "profile")
    payload = {"messages": [PROFILE_RULE] + last_turn(state["messages"])}
    if item:
        payload["existing"] = {"Profile": item.value}
    result = profile_extractor().invoke(payload, config={"recursion_limit": 6})
    runtime.store.put(namespace, "profile", result["responses"][0].model_dump())


def build_store(kind: str = "sqlite", path: str = "memory.db"):
    if kind == "memory":
        return InMemoryStore()
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    store = SqliteStore(conn)
    store.setup()
    return store


def sqlite_checkpointer(path: str = "assistant.db") -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def build_agent(checkpointer=None, summarization: bool = True, store=None, approvals=None):
    prompt = [desk_prompt] if summarization or store is not None else []
    fold = [make_summarize(cheap_model())] if summarization else []
    guest = [patch_profile] if store is not None else []
    guard = [HumanInTheLoopMiddleware(interrupt_on=approvals)] if approvals else []
    tools = TOOLS + (MEMORY_TOOLS if store is not None else [])
    return create_agent(cheap_model(), tools, system_prompt=system_prompt(),
                        checkpointer=checkpointer, store=store,
                        middleware=[log_tool_call, *prompt, *fold, *guest, *guard])


def print_schemas() -> None:
    for spec in TOOLS:
        print(f"### {spec.name}")
        print(json.dumps(convert_to_openai_tool(spec), indent=2))
        print()


def trace_metadata(thread_id: str, tags: list[str] | None = None) -> dict:
    prompt, _ = prompt_source()
    metadata = {
        "langfuse_session_id": thread_id,
        "langfuse_user_id": LANGFUSE_USER,
        "langfuse_tags": tags or ["session-07"],
    }
    if prompt is not None:
        metadata["langfuse_prompt"] = prompt
    return metadata


def new_trace_handler():
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def ask(agent, text: str, thread_id: str, callbacks: list | None = None,
        user: str = "guest", tags: list[str] | None = None) -> dict:
    return agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config={"configurable": {"thread_id": thread_id, "user_id": user},
                "recursion_limit": 25, "callbacks": callbacks or [],
                "metadata": trace_metadata(thread_id, tags)},
    )


def trace_callbacks() -> list:
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return []
    from langfuse import get_client

    try:
        up = get_client().auth_check()
    except Exception as error:
        up = type(error).__name__
    print("langfuse:", os.getenv("LANGFUSE_HOST"), "| up:", up)
    handler = new_trace_handler() if up is True else None
    return [handler] if handler else []


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--publish-prompt" in args:
        publish_prompt()
        raise SystemExit
    if "--schemas" in args:
        print_schemas()
        raise SystemExit
    if "--mermaid" in args:
        print(build_agent(store=InMemoryStore()).get_graph().draw_mermaid())
        raise SystemExit

    def option(flag: str, default: str) -> str:
        if flag not in args:
            return default
        at = args.index(flag)
        if at + 1 >= len(args):
            raise SystemExit(f"{flag} needs a value")
        value = args[at + 1]
        del args[at:at + 2]
        return value

    thread, user = option("--thread", "desk"), option("--user", "guest")
    store = build_store(option("--store", "sqlite"))
    agent = build_agent(sqlite_checkpointer(), store=store)
    question = " ".join(args) or "What course can I take just to relax? Enroll me as Sasha."
    callbacks = trace_callbacks()
    try:
        state = ask(agent, question, thread, callbacks, user)
        for message in last_turn(state["messages"]):
            message.pretty_print()
        summary = state.get("summary", "")
        print(f"[state] thread={thread} | {len(state['messages'])} messages | summary: "
              f"{summary[:80] + '...' if summary else 'none yet'}")
    except GraphRecursionError:
        print("Stopped: the agent hit the step limit without a final answer.")
    card = store.get(("profiles", user), "profile")
    facts = [hit.value["fact"] for hit in store.search(("memories", user))]
    print(f"[profile] {user}: {json.dumps(card.value) if card else 'nothing yet'}")
    print(f"[memories] {user}: {'; '.join(facts) or 'none yet'}")
    if callbacks:
        from langfuse import get_client

        get_client().flush()
