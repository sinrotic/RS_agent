from __future__ import annotations

from rs_core.serving.api import app

create_app = app.create_app
fastapi_app = app.app
get_service = app.get_service

__all__ = ["app", "create_app", "fastapi_app", "get_service"]
