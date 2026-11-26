from langchain_core.messages import AIMessage
from langgraph.types import Command


def test_editor_revision_replaces_team_and_merges_private_interviews():
    from research import Analyst, Perspectives, build_research

    class TeamModel:
        def with_structured_output(self, schema, *, method):
            assert schema is Perspectives
            return self

        def invoke(self, prompt, config=None):
            names = ("Ada", "Grace", "Linus") if "add a commuter" in prompt else (
                "Ada", "Grace", "Barbara"
            )
            return Perspectives(analysts=[Analyst(name=name, role=name) for name in names])

    class InterviewModel:
        def invoke(self, messages, config=None):
            system = messages[0].content
            if "one short question" in system:
                return AIMessage(content="Which courses cover LLM agents?")
            assert "[Doc 2]" in system
            assert "[Doc 4]" not in system
            assert "not the full catalog" in system
            return AIMessage(content="LLM Agents covers the topic [Doc 2].")

    class ReportModel:
        def invoke(self, prompt, config=None):
            assert "Barbara:" not in prompt
            assert all(f"{name}:" in prompt for name in ("Ada", "Grace", "Linus"))
            assert "The catalog contains 5 courses." in prompt
            assert "Courses starting at or after 16:00: sc-01, sc-02, sc-04." in prompt
            assert "[Doc 4] Catalog: sc-04 Board Game Theory" in prompt
            assert "[Doc 5] Catalog: sc-05 Functional Programming" in prompt
            return AIMessage(content="Consider LLM Agents [Doc 2].")

    graph = build_research(TeamModel(), InterviewModel(), ReportModel())
    config = {"configurable": {"thread_id": "test"}, "recursion_limit": 50}
    state = graph.invoke({"topic": "Pick special courses", "feedback": ""}, config)
    assert state["__interrupt__"] and not state.get("sections")
    assert [analyst["name"] for analyst in state["analysts"]] == ["Ada", "Grace", "Barbara"]

    state = graph.invoke(Command(resume="add a commuter"), config)
    assert state["__interrupt__"] and not state.get("sections")
    assert [analyst["name"] for analyst in state["analysts"]] == ["Ada", "Grace", "Linus"]

    state = graph.invoke(Command(resume="approve"), config)
    assert "__interrupt__" not in state
    assert [section.split(":", 1)[0] for section in state["sections"]] == ["Ada", "Grace", "Linus"]
    assert state["report"] == "Consider LLM Agents [Doc 2]."
    assert {"messages", "docs", "analyst"}.isdisjoint(state)


def test_search_ignores_question_words_and_does_not_invent_sources():
    from research import stub_search

    hits = stub_search("What do you know about the Friday schedule for LLM agents?")
    assert hits.startswith("[Doc 2]")
    assert "[Doc 2]" not in stub_search("quadratic equations?")
    assert stub_search("quadratic equations?").startswith("No documents matched.")
