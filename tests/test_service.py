import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

import service
from bot import data_events, plain_text


class FakeGraph:
    def __init__(self):
        self.config = None

    async def astream(self, payload, config, stream_mode):
        self.config = config
        yield AIMessageChunk(content="hello"), {"langgraph_node": "model"}
        yield AIMessageChunk(content="ignored"), {"langgraph_node": "tools"}
        yield AIMessageChunk(content=" world"), {"langgraph_node": "model"}


def test_chat_streams_only_model_messages(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    graph = FakeGraph()
    monkeypatch.setattr(service, "build_service_graph", lambda checkpointer: graph)

    with TestClient(service.app) as client:
        with client.stream("POST", "/chat/t-1", json={"text": "hi"},
                           headers={"X-User-Id": "42"}) as reply:
            body = "".join(reply.iter_text())

        assert reply.status_code == 200
        assert reply.headers["content-type"].startswith("text/event-stream")
        assert "data: hello\n" in body
        assert "data:  world\n" in body
        assert "ignored" not in body
        assert body.endswith("data: [DONE]\n\n")
        assert graph.config["configurable"]["user_id"] == "42"

        assert client.post("/chat/t-2", json={"text": "   "}).status_code == 422

        health = client.get("/health")
        assert health.json() == {"status": "ok", "lane": "memory"}


def test_multiline_chunk_uses_one_sse_event():
    assert service.sse_message("a\nb") == "data: a\ndata: b\n\n"
    assert service.sse_message("a\r\nb") == "data: a\ndata: b\n\n"


class FakeReply:
    def __init__(self, lines):
        self.lines = lines
        self.content = self

    def __aiter__(self):
        return self._lines()

    async def _lines(self):
        for line in self.lines:
            yield line


def test_data_events_join_lines_and_split_events():
    async def collect():
        reply = FakeReply([b"data: a\n", b"data: b\n", b"\n",
                           b"data: [DONE]\n", b"\n"])
        return [event async for event in data_events(reply)]

    assert asyncio.run(collect()) == ["a\nb", "[DONE]"]


def test_plain_text_renders_table_and_bold():
    markdown = "| Курс | Места |\n|---|---|\n| **LLM** | 25 |"
    assert plain_text(markdown) == "Курс · Места\nLLM · 25"
