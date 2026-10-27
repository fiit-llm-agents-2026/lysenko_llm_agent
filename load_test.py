from langchain_core.callbacks import BaseCallbackHandler
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

import run
from run import ask, build_agent

DIALOGUE = [
    "Hi! I'm Sasha, second-year master's student in applied math, I study at the CS faculty. What courses are about AI?",
    "When does the LLM Agents course meet and where?",
    "Enroll me in LLM Agents, please.",
    "Is there anything about computer vision?",
    "Who teaches the Computer Vision course?",
    "How many seats are free in Computer Vision?",
    "Fine, enroll me there as well.",
    "What about something chill, to relax after classes?",
    "When is the Chill Course?",
    "I will think about it. Anything about math?",
    "Which textbooks does Board Game Theory use? If you do not know, say so.",
    "Where is Board Game Theory held?",
    "Enroll me in Board Game Theory.",
    "Is there a course about coding or Haskell?",
    "When does Functional Programming meet?",
    "How many seats does Functional Programming have?",
    "Hold Functional Programming for now; I need to check my schedule.",
    "Anything on Fridays?",
    "Is LLM Agents in the afternoon?",
    "Which room is Computer Vision in again?",
    "Let me recap: which courses am I enrolled in so far?",
    "My friend Tim wants to join LLM Agents. Enroll him too.",
    "And enroll Tim in the Chill Course as well.",
    "How many seats are left in LLM Agents now?",
    "Is there a second AI course besides LLM Agents and Computer Vision?",
    "Is the Chill Course related to AI in any way?",
    "Which of my courses is the earliest in the week?",
    "And the latest one?",
    "Do any two of my courses fall on the same day?",
    "Tim changed his mind about the Chill Course. Can you unenroll him?",
    "Okay, noted. Is there a course about games?",
    "Do I need to bring anything to Board Game Theory?",
    "Is Functional Programming in Room 214 or somewhere else?",
    "My schedule is fine. Enroll me in Functional Programming.",
    "Enroll Tim in Functional Programming too.",
    "How many seats does Functional Programming have left now?",
    "Which of my courses is on Wednesday?",
    "Is there anything about images other than Computer Vision?",
    "Alright, enroll me in the Chill Course after all.",
    "What time does the Chill Course start?",
    "Is the student club far from Room 412? If you do not know, say so.",
    "How many courses am I enrolled in now?",
    "List them with days and times, please.",
    "Which of them has the fewest free seats right now?",
    "Is there a course about haskell besides Functional Programming?",
    "Are there any courses on Saturday?",
    "What was the first course I asked you about today?",
    "Which courses is Tim enrolled in?",
    "Thanks, that is all for today.",
    "One last check: what is my name, which year am I in, what do I study and at which faculty?",
]


class UsageMeter(BaseCallbackHandler):
    def __init__(self):
        self.calls = []

    def on_llm_end(self, response, **kwargs):
        usage = response.generations[0][0].message.usage_metadata or {}
        self.calls.append((usage.get("input_tokens", 0), usage.get("output_tokens", 0)))


def drive(label: str, summarization: bool) -> list[tuple[int, int, int]]:
    run.ENROLLMENTS.clear()
    agent = build_agent(InMemorySaver(), summarization=summarization)
    rows = []
    print(f"\n== {label} ==")
    print("turn  calls  input  output  largest prompt  messages in state")
    for turn, line in enumerate(DIALOGUE, 1):
        meter = UsageMeter()
        state = ask(agent, line, f"load-{label}", [meter, CallbackHandler()])
        inp = sum(i for i, _ in meter.calls)
        out = sum(o for _, o in meter.calls)
        largest = max(i for i, _ in meter.calls)
        rows.append((inp, out, largest))
        print(f"{turn:4}  {len(meter.calls):5}  {inp:5}  {out:6}  {largest:14}  "
              f"{len(state['messages']):17}", flush=True)
    print("turn 50 reply:", state["messages"][-1].content)
    return rows


if __name__ == "__main__":
    print("langfuse:", get_client().auth_check())
    buffer = drive("buffer", summarization=False)
    summary = drive("summary", summarization=True)
    get_client().flush()
    print("\n== full buffer vs summarization, 50 turns each ==")
    for name, idx in (("input tokens", 0), ("output tokens", 1)):
        b, s = sum(r[idx] for r in buffer), sum(r[idx] for r in summary)
        print(f"total {name}: buffer {b} | summary {s} | {100 * (b - s) / b:.0f}% less")
    b, s = max(r[2] for r in buffer), max(r[2] for r in summary)
    print(f"largest prompt: buffer {b} | summary {s}")
    print(f"turn 50 prompt: buffer {buffer[-1][2]} | summary {summary[-1][2]}")
