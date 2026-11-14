from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from run import make_summarize


def test_summarize_folds_old_messages():
    messages = []
    for index in range(10):
        messages += [HumanMessage(f"old question {index}"), AIMessage(f"old answer {index}")]
    messages.append(HumanMessage("the latest question"))

    node = make_summarize(FakeListChatModel(responses=["a short summary"]))
    update = node.after_agent({"messages": messages}, None)

    assert update["summary"] == "a short summary"
    assert len(update["messages"]) == 20
    assert all(isinstance(message, RemoveMessage) for message in update["messages"])
