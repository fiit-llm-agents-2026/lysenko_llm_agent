import argparse
import json

from langgraph.types import Command

from run import ENROLLMENTS, GATED, build_agent, build_store, sqlite_checkpointer


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fork one checkpoint into a new continuation.")
    parser.add_argument("--thread", default="desk")
    parser.add_argument("--user", default="guest")
    parser.add_argument("--store", default="sqlite", choices=["sqlite", "memory", "none"])
    parser.add_argument("--list", action="store_true", help="print checkpoint history and exit")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--at", help="checkpoint id to fork from, full or last 8 characters")
    parser.add_argument("--decision", choices=["approve", "edit", "reject"], default="approve")
    parser.add_argument("--args", default="", help="JSON args for an edit decision")
    parser.add_argument("--reason", default="", help="reason for a reject decision")
    return parser.parse_args()


def short(config: dict) -> str:
    return config["configurable"]["checkpoint_id"][-8:]


def find(history: list, wanted: str):
    for snapshot in history:
        checkpoint_id = snapshot.config["configurable"]["checkpoint_id"]
        if checkpoint_id == wanted or checkpoint_id.endswith(wanted):
            return snapshot
    raise SystemExit(f"no checkpoint {wanted!r} in thread {ARGS.thread}")


def print_history(history: list) -> None:
    print("step  next                                      checkpoint  parent    messages  gate")
    for snapshot in history[:ARGS.limit]:
        parent = short(snapshot.parent_config) if snapshot.parent_config else "-"
        gate = "pending" if snapshot.tasks and snapshot.tasks[0].interrupts else ""
        print(f"{snapshot.metadata['step']:4}  {str(snapshot.next):40}  {short(snapshot.config):10}  "
              f"{parent:8}  {len(snapshot.values.get('messages', [])):8}  {gate}")


def decision() -> dict:
    if ARGS.decision == "edit":
        return {"type": "edit",
                "edited_action": {"name": GATED_TOOL, "args": json.loads(ARGS.args)}}
    if ARGS.decision == "reject":
        return {"type": "reject", **({"message": ARGS.reason} if ARGS.reason else {})}
    return {"type": "approve"}


def main() -> None:
    agent = build_agent(
        sqlite_checkpointer(),
        store=None if ARGS.store == "none" else build_store(ARGS.store),
        approvals=GATED,
    )
    config = {"configurable": {"thread_id": ARGS.thread, "user_id": ARGS.user},
              "recursion_limit": 25}
    history = list(agent.get_state_history(config))
    if ARGS.list:
        print_history(history)
        return
    if ARGS.at:
        fork_at = find(history, ARGS.at)
    else:
        paused = next((s for s in history if s.tasks and s.tasks[0].interrupts), None)
        if paused is None or paused.parent_config is None:
            raise SystemExit("no paused gate in this thread; pass --at a checkpoint id")
        fork_at = find(history, short(paused.parent_config))
    print(f"[fork] step {fork_at.metadata['step']} | next {fork_at.next} | "
          f"checkpoint ..{short(fork_at.config)}")
    if fork_at.tasks and fork_at.tasks[0].interrupts:
        print("[warn] this checkpoint is already a pause; prefer its parent")

    paused = agent.invoke(None, config={**fork_at.config, "recursion_limit": 25})
    if "__interrupt__" not in paused:
        raise SystemExit("the replay ended without a gate; choose another checkpoint")
    request = paused["__interrupt__"][0]
    print(f"[gate] {json.dumps(request.value['action_requests'], ensure_ascii=False)}")
    pause_config = agent.get_state(config).config
    print(f"[pause] checkpoint ..{short(pause_config)}")

    ENROLLMENTS.clear()
    final = agent.invoke(Command(resume={"decisions": [decision()]}), config=pause_config)
    print(f"[decision] {ARGS.decision}")
    print(f"[answer] {final['messages'][-1].content}")
    print(f"[enrollments] {json.dumps(ENROLLMENTS, ensure_ascii=False)}")
    print(f"[branch] checkpoint ..{short(agent.get_state(config).config)}")


ARGS = options()
GATED_TOOL = next(iter(GATED))

if __name__ == "__main__":
    main()
