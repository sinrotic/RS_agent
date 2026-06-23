from __future__ import annotations

from rs_core.serving.api import app

fastapi_app = app.app
get_service = app.get_service

__all__ = ["app", "fastapi_app", "get_service"]
