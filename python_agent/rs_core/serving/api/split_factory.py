from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from rs_core.serving.api.routers import agent, online


EngineDependency = Callable[[], Any]


def create_online_app(get_online_engine: EngineDependency) -> FastAPI:
    app = FastAPI(title="RS Agent Online Service")
    app.include_router(online.create_router(get_online_engine))
    return app


def create_agent_app(get_agent_engine: EngineDependency) -> FastAPI:
    app = FastAPI(title="RS Agent Agent Service")
    app.include_router(agent.create_router(get_agent_engine))
    return app


__all__ = ["create_agent_app", "create_online_app"]
