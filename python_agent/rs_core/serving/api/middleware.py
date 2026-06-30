from __future__ import annotations

from fastapi import FastAPI, Request

from rs_core.serving.api.dependencies import REQUEST_ID_HEADER, normalized_request_id


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = normalized_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
