"""Domain adapters for the generic agent runtime contracts."""

from rs_core.agent.adapters.memory import MemoryAgentAdapter, MemoryAgentConfig, MemoryAgentShadowReport, MemoryAgentSupport
from rs_core.agent.adapters.rag import RagAgentAdapter, RagAgentConfig, RagAgentInvocation, RagAgentShadowReport, RagAgentSupport
from rs_core.agent.adapters.recommendation import RecommendationShadowAdapter, RecommendationShadowReport

__all__ = [
    "MemoryAgentAdapter",
    "MemoryAgentConfig",
    "MemoryAgentShadowReport",
    "MemoryAgentSupport",
    "RagAgentAdapter",
    "RagAgentConfig",
    "RagAgentInvocation",
    "RagAgentShadowReport",
    "RagAgentSupport",
    "RecommendationShadowAdapter",
    "RecommendationShadowReport",
]
