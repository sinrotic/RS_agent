from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from rs_core.agent.contracts import DialogueResult, ExplanationResult
from rs_core.agent.dialogue import plan_dialogue_turn
from rs_core.agent.explanation import build_recommendation_explanation
from rs_core.agent.tools import validate_call_rag_agent_arguments
from rs_core.data.clients import DataClient, KnowledgeDataClient, MemoryDataClient
from rs_core.online.clients import OnlineRecommendationClient


class AgentServiceLike(Protocol):
    def start_session(self, user_id: str | None = None, request_id: str | None = None) -> str: ...
    def chat(self, session_id: str, message: str, request_id: str | None = None) -> Any: ...
    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None, request_id: str | None = None) -> Any: ...
    def end_session(self, session_id: str, reason: str = "unknown", client_event: str | None = None, write_summary: bool = True, request_id: str | None = None) -> dict[str, Any]: ...
    def export_session(self, session_id: str) -> dict[str, Any]: ...
    def readiness(self) -> dict[str, Any]: ...


@dataclass
class AgentOrchestrationEngine:
    """Agent/RAG/dialogue orchestration boundary; recommendation is accessed through clients."""

    service: AgentServiceLike | None = None
    online_client: OnlineRecommendationClient = field(default_factory=OnlineRecommendationClient)
    data_client: DataClient = field(default_factory=DataClient)
    knowledge_client: KnowledgeDataClient = field(default_factory=KnowledgeDataClient)
    memory_client: MemoryDataClient = field(default_factory=MemoryDataClient)

    def ready(self) -> dict[str, Any]:
        dependencies = {
            "online_client": type(self.online_client).__name__,
            "data_client": type(self.data_client).__name__,
            "knowledge_client": type(self.knowledge_client).__name__,
            "memory_client": type(self.memory_client).__name__,
        }
        if self.service is None:
            return {
                "status": "degraded",
                "engine": "AgentOrchestrationEngine",
                "reason": "no_service_bound",
                "dependencies": dependencies,
            }
        readiness = self.service.readiness()
        readiness.setdefault("dependencies", dependencies)
        return readiness

    def start_session(self, user_id: str | None = None, request_id: str | None = None) -> str:
        if self.service is None:
            return user_id or "local-session"
        return self.service.start_session(user_id, request_id=request_id)

    def chat(self, session_id: str, message: str, request_id: str | None = None) -> dict[str, Any]:
        if self.service is None:
            return DialogueResult(session_id=session_id, display={"assistant_message": "agent engine is available without a bound service", "items": []}).to_dict()
        result = self.service.chat(session_id, message, request_id=request_id)
        return DialogueResult(session_id=result.session_id, display=result.display).to_dict()

    def plan_dialogue(self, message: str, session: Any, explanation_item_id: str | None = None) -> dict[str, Any]:
        plan = plan_dialogue_turn(message, session, explanation_item_id=explanation_item_id)
        return asdict(plan)

    def validate_rag_agent_call(self, arguments: dict[str, Any] | None, phase: str = "") -> dict[str, Any]:
        return asdict(validate_call_rag_agent_arguments(arguments, phase=phase))

    def explain(self, session: Any, item_id: str | None = None) -> dict[str, Any]:
        text = build_recommendation_explanation(session, item_id=item_id)
        session_id = str(getattr(session, "session_id", ""))
        return ExplanationResult(session_id=session_id, item_id=item_id, text=text).to_dict()

    def memory_ref(self, session_id: str) -> dict[str, str]:
        return self.memory_client.session_memory_ref(session_id)

    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        if self.service is None:
            return DialogueResult(session_id=session_id, display={"assistant_message": "feedback recorded by unbound agent engine", "items": []}).to_dict()
        result = self.service.feedback(session_id, action_type, item_id, comment, request_id=request_id)
        return DialogueResult(session_id=result.session_id, display=result.display).to_dict()

    def recommend(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call online recommendation through the public client boundary."""

        return self.online_client.recommend(payload)

    def end_session(self, session_id: str, reason: str = "unknown", client_event: str | None = None, write_summary: bool = True, request_id: str | None = None) -> dict[str, Any]:
        if self.service is None:
            return {"session_id": session_id, "status": "ended", "turn_count": 0, "summary_document": None}
        return self.service.end_session(session_id, reason=reason, client_event=client_event, write_summary=write_summary, request_id=request_id)

    def export_session(self, session_id: str) -> dict[str, Any]:
        if self.service is None:
            return {"session_id": session_id, "user_id": "", "turn_count": 0, "public_timeline": {}, "display_responses": []}
        return self.service.export_session(session_id)

    def rag_query(self, query: str, *, max_chunks: int = 3, source_path: str | None = None) -> dict[str, Any]:
        evidence = []
        if source_path:
            evidence = self.knowledge_client.chunks_from_jsonl(source_path, limit=max_chunks)
        return {
            "query": query,
            "evidence": [chunk.to_dict() for chunk in evidence],
            "evidence_count": len(evidence),
            "max_chunks": max_chunks,
            "data_client": "KnowledgeDataClient",
        }


__all__ = ["AgentOrchestrationEngine", "AgentServiceLike"]
