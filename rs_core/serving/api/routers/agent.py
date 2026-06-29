from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from rs_core.serving.schemas import ChatRequest, EndSessionRequest, FeedbackRequest, RagQueryRequest, StartSessionRequest


EngineDependency = Callable[[], Any]


def create_router(get_agent_engine: EngineDependency) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "agent-service"}

    @router.get("/ready")
    def ready(engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.ready()

    @router.post("/session/start")
    def start_session(request: StartSessionRequest, engine: Any = Depends(get_agent_engine)) -> dict[str, str]:
        return {"session_id": engine.start_session(request.user_id)}

    @router.post("/chat")
    def chat(request: ChatRequest, engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.chat(request.session_id, request.message)

    @router.post("/chat/stream")
    def chat_stream(request: ChatRequest, engine: Any = Depends(get_agent_engine)) -> StreamingResponse:
        return StreamingResponse(
            _chat_stream_events(request, engine),
            media_type="text/event-stream",
        )

    @router.post("/feedback")
    def feedback(request: FeedbackRequest, engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.feedback(request.session_id, request.action_type, request.item_id, request.comment)

    @router.post("/rag/query")
    def rag_query(request: RagQueryRequest, engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.rag_query(request.query, max_chunks=request.max_chunks)

    @router.post("/session/end")
    def end_session(request: EndSessionRequest, engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.end_session(request.session_id, reason=request.reason, client_event=request.client_event, write_summary=request.write_summary)

    @router.get("/session/{session_id}")
    def get_session(session_id: str, engine: Any = Depends(get_agent_engine)) -> dict[str, Any]:
        return engine.export_session(session_id)

    return router


def _chat_stream_events(request: ChatRequest, engine: Any) -> Iterable[str]:
    if hasattr(engine, "stream_chat"):
        yield from engine.stream_chat(request.session_id, request.message)
        return

    result = engine.chat(request.session_id, request.message)
    display = _as_mapping(getattr(result, "display", None) or result.get("display", {}))
    assistant_message = str(display.get("assistant_message", ""))
    if assistant_message:
        yield _sse("token", {"type": "token", "delta": assistant_message})
    yield _sse("done", {"type": "done", "done": True})


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = ["create_router"]
