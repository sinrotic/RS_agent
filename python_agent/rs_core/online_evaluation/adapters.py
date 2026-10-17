"""独立评审模型和真实 Catalog 查询；凭证仅从评价模块专用环境变量读取。"""

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content
from rs_core.offline.evaluation.skill_benchmark.catalog_curation import curate_item


class JsonModel:
    def __init__(self, client, model, *, max_tokens=2400):
        if type(max_tokens) is not int or not 256 <= max_tokens <= 16000:
            raise ValueError("模型输出预算必须为256–16000 tokens")
        self.client, self.model, self.max_tokens = client, model, max_tokens

    def __call__(self, instruction, payload):
        response = self.client.chat_completion(
            model=self.model,
            messages=[{"role": "system", "content": instruction},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            temperature=0, max_tokens=self.max_tokens, response_format={"type": "json_object"},
        )
        return json.loads(first_message_content(response))


def model_from_env():
    url, model = os.environ.get("RS_EVAL_MODEL_BASE_URL"), os.environ.get("RS_EVAL_MODEL")
    if not url or not model:
        return None
    # 不继承推荐 Agent 的模型配置或密钥。
    client = OpenAICompatibleClient(
        base_url=url, api_key_env="RS_EVAL_MODEL_API_KEY", timeout_seconds=30,
        allow_insecure_local_api_base=os.environ.get("RS_EVAL_ALLOW_LOCAL_MODEL_HTTP") == "true",
    )
    return JsonModel(client, model)


class HttpCatalog:
    def __init__(self, base_url, *, currency=None, timeout=5):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Catalog URL 无效")
        self.url = base_url.rstrip("/") + "/internal/catalog/context/item-embedding-texts"
        self.currency, self.timeout = currency, timeout

    def __call__(self, ids):
        if not ids:
            return []
        headers = {"Content-Type": "application/json"}
        token = os.environ.get("RS_EVAL_CATALOG_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.url, data=json.dumps({"item_ids": ids}).encode(),
                          headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Catalog 响应过大")
            rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Catalog 响应无效")
        result = []
        fetched_at = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if not isinstance(row, dict) or row.get("item_id") not in ids:
                raise ValueError("Catalog 返回非请求商品")
            path = row.get("category_path") or []
            if isinstance(path, str):
                path = [part.strip() for part in path.split(">") if part.strip()]
            item = {"item_id": row["item_id"], "title": row.get("title") or "",
                    "category": row.get("category"), "category_path": path,
                    "brand": row.get("brand"), "price": row.get("price"),
                    "currency": self.currency, "facts_observed_at": fetched_at}
            result.append(curate_item(item))
        return result
