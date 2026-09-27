import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"])
MODEL = os.environ["MODEL_CHEAP"]

SYSTEM = """You are a university special course information service. You have one tool at your disposal:
spec_course_find("<words>") — searches for a special course based on a word from its title, topic, or the day of the week it takes place.

Respond strictly in the following format (one block for each step):
Thought: what needs to be determined
Action: spec_course_find("<words>")
Observation: <search result>
Once you have the answer, write:
Final answer: <one or two sentences>"""
STOP_RULE = "\nAfter the Action line STOP and wait: never write the Observation yourself."
QUESTION = "What course can I take just to relax?"

SPEC_COURSES = [
    ("Tuesday", "Chill Course", "chill"),
    ("Friday", "LLM Agents", "llm, ai, agents"),
]

def spec_course_find(argument: str) -> str:
    needle = argument.strip().lower()
    hits = [c for c in SPEC_COURSES if needle in c[0].lower() or needle in c[1].lower() or needle in c[2].lower()]
    if not hits:
        topics = sorted({t.strip() for c in SPEC_COURSES for t in c[2].split(",")})
        return f"No course matching {argument!r}. Try weekday or one topic word: {', '.join(topics)}."
    return "; ".join(f"{c[0]}, {c[1]}, (keywords: {c[2]})" for c in hits)


TOOL = spec_course_find


def parse_action(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Action:"):
            start, end = line.find('"'), line.rfind('"')
            if start != -1 and end > start:
                return line[start + 1 : end]
    return None


def cut_at_observation(text: str) -> str:
    marker = text.find("Observation:")
    return text if marker == -1 else text[:marker].rstrip()


def run(honest: bool = True, steps: int = 5) -> list[str]:
    messages = [{"role": "system", "content": SYSTEM + (STOP_RULE if honest else "")},
                {"role": "user", "content": QUESTION}]
    transcript = [f"Question: {QUESTION}"]
    for _ in range(steps):
        answer = client.chat.completions.create(
            # pre-set high: hidden reasoning is billed from this budget too
            model=MODEL, messages=messages, max_completion_tokens=2000
        )
        choice = answer.choices[0]
        reply = choice.message.content or ""
        # a budget bug, not a parser bug: name it
        if not reply and choice.finish_reason == "length":
            raise RuntimeError(
                "Empty reply at the length limit: the budget went on hidden "
                "reasoning, not on your parser. Raise max_completion_tokens."
            )
        if honest:
            reply = cut_at_observation(reply)
        transcript.append(reply)
        print(reply)

        argument = parse_action(reply)
        if argument is None:
            break

        observation = f"Observation: {TOOL(argument)}"
        transcript.append(observation)
        print(observation)
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": observation})
    return transcript


if __name__ == "__main__":
    # --break removes both safeties: the second transcript you commit
    run(honest="--break" not in sys.argv)