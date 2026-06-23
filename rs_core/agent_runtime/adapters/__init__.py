"""Domain adapters for the generic agent runtime contracts."""

from rs_core.agent_runtime.adapters.memory import MemoryAgentAdapter, MemoryAgentConfig, MemoryAgentShadowReport, MemoryAgentSupport
from rs_core.agent_runtime.adapters.rag import RagAgentAdapter, RagAgentConfig, RagAgentShadowReport, RagAgentSupport
from rs_core.agent_runtime.adapters.recommendation import RecommendationShadowAdapter, RecommendationShadowReport

__all__ = [
    "MemoryAgentAdapter",
    "MemoryAgentConfig",
    "MemoryAgentShadowReport",
    "MemoryAgentSupport",
    "RagAgentAdapter",
    "RagAgentConfig",
    "RagAgentShadowReport",
    "RagAgentSupport",
    "RecommendationShadowAdapter",
    "RecommendationShadowReport",
]
