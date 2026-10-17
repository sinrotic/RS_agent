"""独立旁路接收模块；管理接口始终鉴权，不继承 demo 的宽松认证。"""

import hmac
import json
import os

from fastapi import FastAPI, HTTPException, Request

from .adapters import HttpCatalog, model_from_env
from .requirements import RequirementExtractor
from .service import MAX_EVENT_BYTES, OnlineEvaluation


def configured_evaluation():
    path, salt, url = (os.environ.get(name) for name in (
        "RS_EVAL_DB", "RS_EVAL_IDENTITY_SALT", "RS_EVAL_CATALOG_BASE_URL"
    ))
    if not path or not salt or not url:
        raise ValueError("需要配置 RS_EVAL_DB、RS_EVAL_IDENTITY_SALT、RS_EVAL_CATALOG_BASE_URL")
    model = model_from_env()
    return OnlineEvaluation(path, salt=salt,
                            catalog=HttpCatalog(url, currency=os.environ.get("RS_EVAL_CATALOG_CURRENCY")),
                            extractor=RequirementExtractor(model), judge=model)


def create_app(evaluation=None, *, token=None):
    app = FastAPI(title="RS Agent Online Evaluation Shadow")
    # 不在 import/app 构建期间创建 DB 或调用模型，方便独立测试和 fail-closed 启动。
    state = {"evaluation": evaluation}

    def require_access(request):
        expected = token if token is not None else os.environ.get("RS_EVAL_INGEST_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        if not expected:
            raise HTTPException(503, "评价接收凭证未配置")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
            raise HTTPException(401, "评价访问需要专用凭证")
        if state["evaluation"] is None:
            try:
                state["evaluation"] = configured_evaluation()
            except ValueError:
                raise HTTPException(503, "评价模块配置不完整") from None
        return state["evaluation"]

    async def body(request):
        buffer = bytearray()
        async for chunk in request.stream():
            buffer.extend(chunk)
            if len(buffer) > MAX_EVENT_BYTES:
                raise HTTPException(413, "评价事件过大")
        try:
            return json.loads(buffer)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, "无效 JSON") from None

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "read_only_shadow", "auto_deploy": False}

    @app.post("/internal/evaluation/turns", status_code=202)
    async def submit(request: Request):
        module = require_access(request)
        try:
            return module.submit(await body(request))
        except ValueError:
            raise HTTPException(422, "无效或冲突的评价事件") from None

    @app.get("/internal/evaluation/turns/{turn_key}")
    def report(turn_key: str, request: Request):
        try:
            return require_access(request).report(turn_key)
        except KeyError:
            raise HTTPException(404, "评价记录不存在") from None

    @app.post("/internal/evaluation/turns/{turn_key}/feedback")
    async def feedback(turn_key: str, request: Request):
        module = require_access(request)
        try:
            return module.feedback(turn_key, await body(request))
        except KeyError:
            raise HTTPException(404, "评价记录不存在") from None
        except ValueError:
            raise HTTPException(422, "无效或冲突的反馈事件") from None

    @app.get("/internal/evaluation/candidates")
    def candidates(request: Request):
        return {"candidates": require_access(request).candidates(), "auto_deploy": False}

    @app.get("/internal/evaluation/status")
    def diagnostics(request: Request):
        return require_access(request).diagnostics()

    @app.post("/internal/evaluation/turns/{turn_key}/retry")
    def retry(turn_key: str, request: Request):
        try:
            return require_access(request).retry_failed(turn_key)
        except KeyError:
            raise HTTPException(404, "评价记录不存在") from None
        except ValueError:
            raise HTTPException(409, "仅允许重试失败的评价") from None

    return app


app = create_app()
