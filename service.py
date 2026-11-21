"""HTTP door to the special-courses graph: SSE chat over a Postgres checkpointer."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

from run import build_agent, build_store, new_trace_handler, trace_metadata

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
STORE_PATH = DATA_DIR / "memory.db"


class ChatIn(BaseModel):
    text: str = Field(min_length=1)


def build_service_graph(checkpointer):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = build_store("sqlite", str(STORE_PATH))
    return build_agent(checkpointer, store=store)


def flush_traces() -> None:
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass


def sse_message(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(f"data: {line}\n" for line in normalized.split("\n")) + "\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = os.getenv("DATABASE_URL")
    if url:
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            app.state.graph = build_service_graph(saver)
            app.state.lane = "postgres"
            yield
    else:
        app.state.graph = build_service_graph(InMemorySaver())
        app.state.lane = "memory"
        yield
    flush_traces()


app = FastAPI(title="special-courses-agent", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "lane": getattr(request.app.state, "lane", "starting")}


@app.post("/chat/{thread_id}")
async def chat(thread_id: str, body: ChatIn, request: Request) -> StreamingResponse:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")
    try:
        handler = new_trace_handler()
    except Exception:
        handler = None
    source = "telegram" if request.headers.get("x-client") == "telegram" else "api"
    user_id = request.headers.get("x-user-id") or os.getenv("LANGFUSE_USER_ID") or "guest"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
        },
        "recursion_limit": 25,
        "metadata": {
            **trace_metadata(thread_id, ["session-08", source]),
            "langfuse_trace_name": f"session-08 {source}",
        },
        "callbacks": [handler] if handler else [],
    }

    async def events():
        try:
            stream = request.app.state.graph.astream(
                {"messages": [{"role": "user", "content": body.text}]},
                config=config,
                stream_mode="messages",
            )
            async for message, metadata in stream:
                if (metadata.get("langgraph_node") == "model"
                        and isinstance(message.content, str) and message.content):
                    yield sse_message(message.content)
        except Exception as error:
            yield sse_message(f"[ERROR] {type(error).__name__}: {error}")
        finally:
            flush_traces()
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
