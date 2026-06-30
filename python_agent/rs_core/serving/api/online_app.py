from __future__ import annotations

from fastapi import FastAPI

from rs_core.serving.api.split_factory import create_online_app
from rs_core.serving.runtime.split_engines import get_online_engine
from rs_core.serving.schemas import RankRequest


def create_app() -> FastAPI:
    return create_online_app(get_online_engine)


app = create_app()

__all__ = ["RankRequest", "app", "create_app", "get_online_engine"]
