from __future__ import annotations

from fastapi import FastAPI

from rs_core.serving.api.split_factory import create_agent_app
from rs_core.serving.runtime.split_engines import get_agent_engine
from rs_core.serving.schemas import RagQueryRequest


def create_app() -> FastAPI:
    return create_agent_app(get_agent_engine)


app = create_app()

__all__ = ["RagQueryRequest", "app", "create_app", "get_agent_engine"]
