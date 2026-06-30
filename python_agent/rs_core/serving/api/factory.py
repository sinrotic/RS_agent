from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rs_core.serving.api.exceptions import register_exception_handlers
from rs_core.serving.api.middleware import register_middleware
from rs_core.serving.api.routers import demo, recommendation, runtime, simulation


def create_app() -> FastAPI:
    app = FastAPI(title="RS Agent Serving Demo")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(runtime.router)
    app.include_router(recommendation.router)
    app.include_router(demo.router)
    app.include_router(simulation.router)
    return app
