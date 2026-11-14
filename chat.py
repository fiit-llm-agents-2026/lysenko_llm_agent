import argparse
import json
import os
import sys

from langchain_core.messages import AIMessageChunk
from langgraph.types import Command

from run import ENROLLMENTS, GATED, build_agent, build_store, sqlite_checkpointer


def ask(prompt: str) -> str:
    value = input(prompt)
    if not sys.stdin.isatty():
        print(value)
    return value


def decide(prompt: str) -> str:
    try:
        return ask(prompt).strip()
    except EOFError:
        raise SystemExit("\n[exit] no decision; the pause stays in the checkpointer")


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Streaming console client with an approval gate.")
    parser.add_argument("--thread", default="desk")
    parser.add_argument("--user", default="guest")
    parser.add_argument("--store", default="sqlite", choices=["sqlite", "memory", "none"])
    parser.add_argument("--no-gate", action="store_true")
    parser.add_argument("--no-trace", action="store_true")
    return parser.parse_args()


def tracer():
    if os.getenv("LANGFUSE_PUBLIC_KEY") and not ARGS.no_trace:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    return None


def base_config(thread: str, user: str) -> dict:
    return {
        "configurable": {"thread_id": thread, "user_id": user},
        "recursion_limit": 25,
        "metadata": {
            "langfuse_session_id": f"session-06:{thread}",
            "langfuse_user_id": user,
            "langfuse_tags": ["session-06"],
            "langfuse_trace_name": "session-06 gate",
        },
    }


def show_chunk(mode: str, chunk) -> tuple[dict | None, bool]:
    if mode == "messages":
        message, meta = chunk
        if (isinstance(message, AIMessageChunk) and meta.get("langgraph_node") == "model"
                and isinstance(message.content, str) and message.content):
            print(message.content, end="", flush=True)
        return None, True
    pause = None
    for node, update in chunk.items():
        if node == "__interrupt__":
            pause = update
        elif node == "tools":
            for result in update.get("messages", []):
                print(f"\n[{result.name}] {result.content}", flush=True)
    return pause, False


def stream(agent, payload, config: dict) -> dict | None:
    handler = tracer()
    cfg = {**config, "callbacks": [handler]} if handler else config
    pause, printed = None, False
    for mode, chunk in agent.stream(payload, config=cfg, stream_mode=["messages", "updates"]):
        found, tokens = show_chunk(mode, chunk)
        if found:
            pause = found
        printed = printed or tokens
    if printed:
        print()
    if handler and handler.last_trace_id:
        print(f"[trace] {handler.last_trace_id}")
    return pause


def review(payload) -> dict:
    request = payload[0].value
    decisions = []
    for action in request["action_requests"]:
        config = next(c for c in request["review_configs"]
                      if c["action_name"] == action["name"])
        print(f"\n[approval] {action['name']} {json.dumps(action['args'], ensure_ascii=False)}")
        print(f"[allowed] {', '.join(config['allowed_decisions'])}")
        choice = decide("approve / edit / reject / respond [a/e/r/s]: ").lower()
        if choice in ("e", "edit"):
            while True:
                raw = decide("new args as JSON, empty keeps them: ")
                if not raw:
                    args = action["args"]
                    break
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    print("[error] not valid JSON, try again")
                    continue
                if not isinstance(args, dict):
                    print("[error] args must be a JSON object, try again")
                    continue
                break
            decisions.append({"type": "edit",
                              "edited_action": {"name": action["name"], "args": args}})
        elif choice in ("r", "reject"):
            reason = decide("reason, empty means no reason: ")
            decisions.append({"type": "reject", **({"message": reason} if reason else {})})
        elif choice in ("s", "respond"):
            message = decide("answer on behalf of the tool: ")
            decisions.append({"type": "respond", "message": message})
        else:
            decisions.append({"type": "approve"})
    return {"decisions": decisions}


def resume(agent, pause, config: dict) -> None:
    while pause:
        pause = stream(agent, Command(resume=review(pause)), config)


def main() -> None:
    agent = build_agent(
        sqlite_checkpointer(),
        store=None if ARGS.store == "none" else build_store(ARGS.store),
        approvals=None if ARGS.no_gate else GATED,
    )
    config = base_config(ARGS.thread, ARGS.user)
    snapshot = agent.get_state(config)
    if snapshot.tasks and snapshot.tasks[0].interrupts:
        print("[parked] a gate from an earlier process is waiting in the checkpointer")
        resume(agent, snapshot.tasks[0].interrupts, config)
    while True:
        try:
            text = ask("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in ("quit", "exit", "/quit"):
            break
        if not text:
            continue
        pause = stream(agent, {"messages": [{"role": "user", "content": text}]}, config)
        resume(agent, pause, config)
        print(f"[enrollments] {json.dumps(ENROLLMENTS, ensure_ascii=False)}")
    if os.getenv("LANGFUSE_PUBLIC_KEY") and not ARGS.no_trace:
        from langfuse import get_client

        get_client().flush()


ARGS = options()

if __name__ == "__main__":
    main()
