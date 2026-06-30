from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rs_core.serving.application.recommendation_service import SessionNotFoundError
from rs_core.serving.facades import SessionEndedError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFoundError)
    def session_not_found_handler(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}},
        )

    @app.exception_handler(SessionEndedError)
    def session_ended_handler(request: Request, exc: SessionEndedError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "SESSION_ENDED", "message": "Session has already ended"}},
        )
